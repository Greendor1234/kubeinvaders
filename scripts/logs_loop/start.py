#!/usr/bin/env python3
import os
import re
import sys
import json
import time
import redis
import logging
import pathlib
import urllib3
import datetime

from hashlib import sha256
from kubernetes import client
from kubernetes.client.rest import ApiException

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

def create_pod_list(logid: str, api_responses: list, current_regex: str) -> list:
    """
    This function create a list of pods
    """
    webtail_pods = []

    json_re  = json.loads(current_regex)
    regexsha = sha256(current_regex.encode('utf-8')).hexdigest()

    pod_re         = json_re["pod"]
    namespace_re   = json_re["namespace"]
    annotations_re = json_re["annotations"]
    labels_re      = json_re["labels"]
    containers_re  = json_re["containers"]

    log_prefix = f"[logid:{logid}][k-inv][regexmatch]"
    
    for api_response in api_responses:

        pods_status = {}

        for pod in api_response.items:

            if pod.status.phase not in pods_status:
                pods_status[pod.status.phase] = 1
            else:
                pods_status[pod.status.phase] += 1

            r.set(
                f"log_status:{logid}", 
                f"""
                Pods on Pending phase: {pods_status.get('Pending',0)}
                Pods on Succeeded phase: {pods_status.get('Succeeded',0)}
                Pods on Running phase: {pods_status.get('Running',0)}
                """.strip().replace('  ', '')
            )

            if r.exists(f"regex_cmp:{regexsha}:{logid}:{pod.metadata.namespace}:{pod.metadata.name}"):
                cached_regex_match = r.get(f"regex_cmp:{regexsha}:{logid}:{pod.metadata.namespace}:{pod.metadata.name}")
                if cached_regex_match == "maching":
                    webtail_pods.append(pod)
                    regex_match_info = f"[logid:{logid}][k-inv][logs-loop] Taking logs of {pod.metadata.name}. Redis has cached that {current_regex} is good for {pod.metadata.name}"
                    logging.debug(f"[k-inv][regexmatch][logid:{logid}][{cached_regex_match}] IS CACHED IN REDIS")

                else:
                    regex_match_info = f"[logs-loop][logid:{logid}] Skipping logs of {pod.metadata.name}. Redis has cached that {current_regex} is not good for {pod.metadata.name}"
                    logging.debug(regex_match_info)
                    logging.debug(f"[k-inv][regexmatch][logid:{logid}][{cached_regex_match}] IS CACHED IN REDIS")

            else:
                if re.search(rf"{pod_re}", pod.metadata.name) or re.search(r"{pod_re}", pod.metadata.name) or (pod_re == pod.metadata.name):
                    logging.debug(f"{log_prefix} |{pod_re}| |{pod.metadata.name}| MATCHED")
                    regex_key_name = f"regex_cmp:{regexsha}:{logid}:{pod.metadata.namespace}:{pod.metadata.name}"

                    if re.search(f"{namespace_re}", pod.metadata.namespace) or re.search(r"{namespace_re}", pod.metadata.namespace) or (namespace_re == pod.metadata.namespace):
                        logging.debug(f"{log_prefix} |{namespace_re}| |{pod.metadata.namespace}| MATCHED")
                        if re.search(f"{labels_re}", str(pod.metadata.labels)) or re.search(r"{labels_re}", str(pod.metadata.labels)):
                            logging.debug(f"{log_prefix} |{labels_re}| |{str(pod.metadata.labels)}| MATCHED")
                            if re.search(f"{annotations_re}", str(pod.metadata.annotations)) or re.search(r"{annotations_re}", str(pod.metadata.annotations)):
                                logging.debug(f"{log_prefix} |{annotations_re}| |{str(pod.metadata.annotations)}| MATCHED")
                                webtail_pods.append(pod)
                                regex_match_info = f"[logid:{logid}] Taking logs from {pod.metadata.name}. It is compliant with the Regex {current_regex}"
                                r.set(regex_key_name, "matching")
                                logging.debug(regex_match_info)
                            else:
                                logging.debug(f"[logid:{logid}][k-inv][regexmatch] |{annotations_re}| |{str(pod.metadata.annotations)}| FAILED")
                                r.set(regex_key_name, "not_maching")
                        else:
                            logging.debug(f"[logid:{logid}][k-inv][regexmatch] |{labels_re}| |{str(pod.metadata.labels)}| FAILED")
                            r.set(regex_key_name, "not_maching")
                    else:
                        logging.debug(f"[logid:{logid}][k-inv][regexmatch] |{namespace_re}| |{pod.metadata.namespace}| FAILED")
                        r.set(regex_key_name, "not_maching")
                else:
                    logging.debug(f"[logid:{logid}][k-inv][regexmatch] |{pod_re}| |{pod.metadata.name}| FAILED")
                    #r.set(regex_key_name, "not_maching")
    return webtail_pods
                            
def log_cleaner(logid):
    """
    Clean logs from Redis
    """
    if not r.exists(f"do_not_clean_log:{logid}"):
        for key in r.scan_iter(f"log_time:{logid}:*"):
            r.delete(key)
        for key in r.scan_iter(f"log:{logid}:*"):
            r.delete(key)
        r.set(f"do_not_clean_log:{logid}", "1")
        r.expire(f"do_not_clean_log:{logid}", 60)
        r.set(f"log_status:{logid}", f"[k-inv][logs-loop] Logs (id: {logid}) has been cleaned")

def get_regex(logid: str):
    """
    Check if key exists in redis, if not set log_status else return the key
    """
    if not r.exists(f"log_pod_regex:{logid}"):
        r.set(f"log_status:{logid}", f"[k-inv][logs-loop] ERROR. Regex has not been configured or is invalid")
    return r.get(f"log_pod_regex:{logid}")

def compute_line(api_response_line, container):
    """
    TBD
    """
    logging.debug(f"[logid:{logid}] API Response: ||{api_response_line}||")
    logrow = f"""
<div class='row' style='margin-top: 2%; color: #1d1919;'>
    <div class='row' style='font-size: 12px'>
        <hr/>
    </div>
    <div class='row log-title'>
        <div class='col'>Namespace</div>
        <div class='col'>Pod</div>
        <div class='col'>Container</div>
    </div>
    <div class='row'>
        <div class='col'>
            <span class="badge rounded-pill alert-logs-namespace">
                {pod.metadata.namespace}
            </span>
        </div>
        <div class='col'>
            <span class="badge rounded-pill alert-logs-pod">
                {pod.metadata.name}
            </span>
        </div>
        <div class='col'>
            <span class="badge rounded-pill alert-logs-container">
                {container}
            </span>
        </div>
    </div>
</div>
<div class='row log-row'>
    {api_response_line}
</div>
"""
    sha256log = sha256(logrow.encode('utf-8')).hexdigest()

    if not r.exists(f"log:{logid}:{pod.metadata.name}:{container}:{sha256log}"):
        logging.debug(f"[logid:{logid}][k-inv][logs-loop] The key log:{logid}:{pod.metadata.name}:{container}:{sha256log} does not exists. Preparing to store log content")
        if not r.exists(f"logs:chaoslogs-{logid}-count"):
            r.set(f"logs:chaoslogs-{logid}-count", 0)
            r.set(f"logs:chaoslogs-{logid}-0", logrow)
        else:
            latest_chaos_logs_count = int(r.get(f"logs:chaoslogs-{logid}-count"))
            latest_chaos_logs_count = latest_chaos_logs_count + 1
            r.set(f"logs:chaoslogs-{logid}-{latest_chaos_logs_count}", logrow)
            r.set(f"logs:chaoslogs-{logid}-count", latest_chaos_logs_count)

    r.set(f"log:{logid}:{pod.metadata.name}:{container}:{sha256log}", logrow)
    r.set(f"log_time:{logid}:{pod.metadata.name}:{container}", time.time())
    r.expire(f"log:{logid}:{pod.metadata.name}:{container}:{sha256log}", 60)

def redis_connection(filename: str):
    """
    Try to connect with redis through the socket path
    """
    options = {
        "charset"          : "utf-8",
        "decode_responses" : True
    }
    return redis.Redis(unix_socket_path = filename, **options) if pathlib.Path(filename).exists() else redis.Redis("127.0.0.1", **options)

def get_api_responses(current_regex: str, log_prefix: str):
    """
    Return pods for each namespace in the namespace list
    """
    try:
        json_re      = json.loads(current_regex)
        namespace_re = json_re["namespace"]

        logging.debug(f"{log_prefix} Taking list of namespaces")

        n_list = api_instance.list_namespace()
        return [ api_instance.list_namespaced_pod(n.metadata.name) for n in n_list.items if re.search(f"{namespace_re}", n.metadata.name) ]
    except ApiException as e:
        logging.error(e)
        return []
    
def compute_container(container, only_one_container):
    """
    TBD
    """
    logging.debug(f"{log_prefix} Container {container} on pod {pod.metadata.name} has accepted phase for taking logs")
    try:
        if r.exists(f"log_time:{logid}:{pod.metadata.name}:{container}"):
            latest_log_tail_time = float(r.get(f"log_time:{logid}:{pod.metadata.name}:{container}"))
            since = int(time.time() - float(latest_log_tail_time)) + 1
        else:
            latest_log_tail_time = time.time()
            pod_start_time = int(datetime.datetime.timestamp(pod.status.start_time))
            logging.debug(f"{log_prefix} POD's start time {pod_start_time}")
            since = int(time.time() - pod_logs_sec) + 1
        
        logging.debug(f"{log_prefix} pod_start_time_sec is {pod_start_time_sec}")

        if since > pod_start_time_sec:
            return

        logging.debug(f"{log_prefix} Time types: {type(latest_log_tail_time)} {type(time.time())} {type(since)} since={since}")                    
        logging.debug(f"{log_prefix} Calling K8s API for reading logs of {pod.metadata.name} container {container} in namespace {pod.metadata.namespace} since {since} seconds - phase {pod.status.phase}")

        if only_one_container:
            api_response = api_instance.read_namespaced_pod_log(
                name          = pod.metadata.name,
                namespace     = pod.metadata.namespace,
                since_seconds = since
            )
        else:
            api_response = api_instance.read_namespaced_pod_log(
                name          = pod.metadata.name, 
                namespace     = pod.metadata.namespace, 
                since_seconds = since, 
                container     = container
            )

        logging.debug(f"{log_prefix} Computing K8s API response for reading logs of {pod.metadata.name} in namespace {pod.metadata.namespace} - phase {pod.status.phase}")
        logging.debug(f"{log_prefix} {type(api_response)} {api_response}")

        r.set(f"log_time:{logid}:{pod.metadata.name}:{container}", time.time())
        
        if not re.search(r'[\w]+', api_response):
            logging.debug(f"{log_prefix} API Response for reading logs of {pod.metadata.name} in namespace {pod.metadata.namespace} is still empty")
            return

        compute_line(api_response, container)

        for api_response_line in api_response if isinstance(api_response, list) else api_response.splitlines():
            logging.debug(f"{log_prefix} Computing log line {api_response_line}")
            compute_line(api_response_line, container)         

    except ApiException as e:
        logging.debug(f"[k-inv][logs-loop] EXCEPTION {e}")

def compute_pod(pod):
    """
    TBD
    """
    logging.debug(f"{log_prefix} Taking logs from {pod.metadata.name}")
    container_list = [ container.name for container in pod.spec.containers ]
    
    only_one_container = True if len(container_list) == 1 else False

    for container in container_list:
        logging.debug(f"{log_prefix} Listing containers of {pod.metadata.name}. Computing {container} phase: {pod.status.phase}")
        
        if pod.status.phase not in ["Unknown", "Pending"]:
            compute_container(container, only_one_container)

if __name__ == "__main__":
    logging.basicConfig(
        level  = os.environ.get("LOGLEVEL", "DEBUG"),
        format = "%(asctime)s [pod_logs] %(message)s"
    )
    logging.getLogger('kubernetes').setLevel(logging.ERROR)

    logging.debug('Starting script for KubeInvaders taking logs from pods...')

    r = redis_connection('/tmp/redis.sock')

    if os.environ.get("DEV"):
        logging.debug("Setting env var for dev...")

        r.set("log_pod_regex", '{"since": 60, "pod":".*", "namespace":"namespace1", "labels":".*", "annotations":".*", "containers": ".*"}')
        r.set("logs_enabled:aaaa", 1)
        r.expire("logs_enabled:aaaa", 10)
        r.set("programming_mode", 0)

        logging.debug(r.get("log_pod_regex:aaaa"))
        logging.debug(r.get("logs_enabled:aaaa"))

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
    namespace    = "kubeinvaders"

    while True:

        logging.debug("Checking...")

        for key in r.scan_iter("logs_enabled:*"):
            if r.get(key) == "1":
                logid = key.split(":")[1]
                logging.debug(f"Found key {key} and it is enabled.")

                webtail_pods  = []
                current_regex = get_regex(logid)
                log_prefix    = f"[logid:{logid}][k-inv][logs-loop]"

                if not current_regex:
                    continue
                else:
                    logging.debug(f"[k-inv][logs-loop] {key} is using this regex: {current_regex}")

                logging.debug(f"[logid:{logid}] Checking do_not_clean_log Redis key")
                log_cleaner(logid)

                api_responses    = get_api_responses(current_regex, log_prefix)
                webtail_pods     = create_pod_list(logid, api_responses, current_regex)
                json_re          = json.loads(current_regex)
                containers_re    = json_re["containers"]
                webtail_pods_len = len(webtail_pods)
                
                if not r.exists(f"logs:chaoslogs-{logid}-count"):
                    old_logs = r.get(f"logs:chaoslogs-{logid}-0")
                else:
                    latest_chaos_logs_count = int(r.get(f"logs:chaoslogs-{logid}-count"))
                    old_logs = r.get(f"logs:chaoslogs-{logid}-{latest_chaos_logs_count}")

                pod_start_time_sec = int(json_re["pod_start_time_sec"])
                pod_logs_sec       = int(json_re["pod_logs_sec"])

                r.set(f"logs:webtail_pods_len:{logid}", webtail_pods_len)
                r.set(f"pods_match_regex:{logid}", webtail_pods_len)

                logging.debug(f"{log_prefix} Current Regex: {current_regex}")
                
                for pod in webtail_pods:
                    if pod.status.phase in ["Unknown", "Pending"]:
                        continue
                    compute_pod(pod)
        time.sleep(1)
