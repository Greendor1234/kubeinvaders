#!/usr/bin/env python3
"""
This is a helper that allows to monitor the pods used to perform chaos engineering with the Programming Mode
"""
import os
import sys
import json
import time
import time
import redis
import logging
import urllib3
import requests
import datetime

from kubernetes import client
from kubernetes.client.rest import ApiException

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

def do_http_request(url: str, method: str, headers: dict, data: dict) -> requests.Response | str:
    """
    Perform an http request and returns the response if ok else returns an error string
    """
    try:
        response = requests.request(method, url, headers=headers, data=data, verify=False, allow_redirects=True, timeout=10)
        return response
    except requests.exceptions.RequestException as e:
        logging.error(f"Error while sending HTTP request: {e}")
        return "Connection Error"

def check_if_json_is_valid(json_data: dict):
    """
    Try to load a JSON with the json library, if catch an exception return false
    """
    try:
        json.loads(json_data)
    except ValueError:
        return False
    return True

def collect_data_for_projects(key_project_list="chaos_report_project_list"):
    """
    For each project in a list check if exists the correspondent key in redis and performs
    an http request against the url specified, retrieves basic informations of the request
    and register the collected data into redis
    """
    for project in r.get(key_project_list).decode().split(','):
        chaos_program_key = f"chaos_report_project_{project}"

        if r.exists(chaos_program_key) and check_if_json_is_valid(r.get(chaos_program_key)):
            chaos_report_program = json.loads(r.get(chaos_program_key))

            now = datetime.datetime.now()

            response = do_http_request(
                chaos_report_program['chaosReportCheckSiteURL'], 
                chaos_report_program['chaosReportCheckSiteURLMethod'], 
                json.loads(chaos_report_program['chaosReportCheckSiteURLHeaders']), 
                chaos_report_program['chaosReportCheckSiteURLPayload']
            )

            check_url_counter_key      = f"{chaos_report_program['chaosReportProject']}_check_url_counter"
            check_url_status_code_key  = f"{chaos_report_program['chaosReportProject']}_check_url_status_code"
            check_url_elapsed_time_key = f"{chaos_report_program['chaosReportProject']}_check_url_elapsed_time"
            check_url_start_time       = f"{chaos_report_program['chaosReportProject']}_check_url_start_time"

            if not r.get(check_url_counter_key):
                r.set(check_url_counter_key, 0)
            else:
                r.incr(check_url_counter_key)

            if not r.get(check_url_start_time):
                r.set(check_url_start_time, now.strftime("%Y-%m-%d %H:%M:%S"))

            if response == "Connection Error":
                r.set(check_url_status_code_key, "Connection Error")
                r.set(check_url_elapsed_time_key, 0)
            else:
                r.set(check_url_status_code_key, response.status_code)
                r.set(check_url_elapsed_time_key, float(response.elapsed.total_seconds()))

def compare_time(
        pod,
        now: int,
        api_instance,
        pod_time: int, 
        pod_time_key: str, 
        log_kinv_suffix: str,
    ):
    """
    Perform a check between the current timestamp and the pod timestamp, if the difference
    is major than 120 it tries to delete the pod from kubernetes and the key from redis
    """
    logging.debug(f"{log_kinv_suffix} For {pod.metadata.name} comparing now:{now} with pod_time:{pod_time}")

    if (now - pod_time > 120):
        try:
            api_instance.delete_namespaced_pod(pod.metadata.name, namespace = pod.metadata.namespace)
            logging.debug(f"{log_kinv_suffix} Deleting pod {pod.metadata.name}")
            r.delete(pod_time_key)
        except ApiException as e:
            logging.debug(e)

def pod_computation(pod, api_instance):
    """
    Check the pod status and update the redis keys according to checked status 
    """
    log_kinv_suffix      = f"[k-inv][metrics_loop]"
    pod_time_key         = f"pod:time:{pod.metadata.namespace}:{pod.metadata.name}"
    found_pod_log_string = f"{log_kinv_suffix} Found pod {pod.metadata.name}. It is in {pod.status.phase} phase."

    if pod.status.phase in ['Pending', 'Running']:
        logging.debug(f"{found_pod_log_string} Incrementing current_chaos_job_pod Redis key")
        r.incr('current_chaos_job_pod')

    if pod.status.phase not in ['Pending', 'Running'] and not r.exists(pod_time_key):
        logging.debug(f"{found_pod_log_string} Tracking time in {pod_time_key} Redis key")
        r.set(pod_time_key, int(time.time()))

    elif pod.status.phase not in ['Pending', 'Running'] and r.exists(pod_time_key):
        logging.debug(f"{found_pod_log_string} Comparing time in {pod_time_key} Redis key with now")
        
        now      = int(time.time())
        pod_time = int(r.get(pod_time_key))

        compare_time(
            pod, 
            now, 
            pod_time, 
            api_instance,
            pod_time_key, 
            log_kinv_suffix, 
        )

    if pod.metadata.labels.get('chaos-codename'):
        codename = pod.metadata.labels.get('chaos-codename')
        job_name = pod.metadata.labels.get('job-name').replace("-","_")
        exp_name = pod.metadata.labels.get('experiment-name')

        if pod.status.phase in ["Pending", "Running", "Succeeded"]:
            r.set(f"chaos_jobs_status:{codename}:{exp_name}:{job_name}", 1.0)
        else:
            r.set(f"chaos_jobs_status:{codename}:{exp_name}:{job_name}", -1)

        r.set(f"chaos_jobs_pod_phase:{codename}:{exp_name}:{job_name}", pod.status.phase)

if __name__ == "__main__":
    r = redis.Redis(unix_socket_path='/tmp/redis.sock')

    logging.basicConfig(level=os.environ.get("LOGLEVEL", "INFO"))
    logging.getLogger('kubernetes').setLevel(logging.ERROR)

    logging.debug('Starting script for KubeInvaders metrics loop')

    token = os.environ["TOKEN"]

    configuration = client.Configuration()
    configuration.api_key = {"authorization": f"Bearer {token}"}
    configuration.host = sys.argv[1]

    configuration.insecure_skip_tls_verify = True
    configuration.verify_ssl = False

    client.Configuration.set_default(configuration)
    client.Configuration.set_default(configuration)

    api_instance = client.CoreV1Api()
    batch_api    = client.BatchV1Api()

    while True:

        logging.debug("Checking...")

        if r.exists('chaos_report_project_list'):
            collect_data_for_projects()

        try:
            label_selector = "chaos-controller=kubeinvaders"
            api_response   = api_instance.list_pod_for_all_namespaces(label_selector=label_selector)
        except ApiException as e:
            logging.debug(e)

        r.set("current_chaos_job_pod", 0)

        for pod in api_response.items:
            pod_computation(pod, api_instance)

        time.sleep(1)
