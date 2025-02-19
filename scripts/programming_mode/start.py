#!/usr/bin/env python3
"""
This is a helper that allows to create pods used to perform chaos engineering against a kubernetes cluster

Usage:
    python3 start.py [filename] [kubernetes-host]


Develop example:
    python3 start.py experiments.yaml https://${KUBERNETES_SERVICE_HOST}:${KUBERNETES_SERVICE_PORT_HTTPS}
"""
import os
import re
import sys
import yaml
import redis
import string
import random
import urllib3
import logging

from kubernetes import client
from kubernetes.client.rest import ApiException

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

def create_container(image: str, name: str, command: str, args):
    """
    Create a container with specific configuration passed as parameters
    """
    container = client.V1Container(
        image             = image,
        name              = name,
        image_pull_policy = 'IfNotPresent',
        args              = args,
        command           = command
    )

    logging.info(
        f"Created container with name: {container.name}, "
        f"Image: {container.image} and Args: {container.args}"
    )
    return container

def create_pod_template(pod_name: str, additional_labels: dict, container, exp_name: str, codename: str):
    """
    Create a pod template with specific configuration passed as parameters
    """
    pod_labels = {
        "chaos-controller": "kubeinvaders", 
        "experiment-name" : exp_name, 
        "chaos-codename"  : codename
    }
    pod_labels.update(additional_labels)

    pod_template = client.V1PodTemplateSpec(
        spec     = client.V1PodSpec(
            restart_policy = "Never",
            containers     = [container]
        ),
        metadata = client.V1ObjectMeta(
            name   = pod_name,
            labels = pod_labels
        ),
    )
    return pod_template

def create_job(job_name: str, pod_template, codename: str):
    """
    Create a job with specific configuration passed as parameters
    """
    metadata = client.V1ObjectMeta(
        name   = job_name,
        labels = {
            "chaos-controller": "kubeinvaders",
            "chaos-codename"  : codename
        }
    )

    job = client.V1Job(
        api_version = "batch/v1",
        kind        = "Job",
        metadata    = metadata,
        spec        = client.V1JobSpec(
            backoff_limit = 0,
            template      = pod_template
        ),
    )
    return job

def parse_yaml():
    """
    Try to parse a yaml with the relative library, if ok returns the parsed yaml else quit
    """
    with open(sys.argv[1], 'r') as stream:
        try:
            logging.info('Trying to parse chaos program...')
            return yaml.safe_load(stream)
        except yaml.YAMLError as e:
            logging.error(f"Invalid YAML syntax, please fix choas program code cause: {e}")
            quit()

def perform_experiment(exp: dict, parsed_yaml: dict):
    """
    It creates inside the cluster the jobs defined in the yaml
    """
    namespace = "kubeinvaders"
    prom_regex = "[a-zA-Z_:][a-zA-Z0-9_:]*"
    codename   = parsed_yaml["chaos-codename"]

    for times in range(exp["loop"]):
        logging.info(f"Processing the experiment {exp}, iteration: {times}")

        job_attrs = parsed_yaml["k8s_jobs"][exp["k8s_job"]]
        args      = [ str(arg) for arg in job_attrs['args'] ]

        logging.info(f"args = {args}, command = {job_attrs['command']}, image = {job_attrs['image']}, k8s_job = {exp['k8s_job']}")

        if not re.fullmatch(prom_regex, exp["name"]):
            ret = f"Invalid name for experiment: {exp['name']}, please match Prometheus metric name format '[a-zA-Z_:][a-zA-Z0-9_:]*'"
            logging.info(ret)
            quit()

        container = create_container(
            image   = job_attrs['image'], 
            name    = exp['k8s_job'],
            command = [job_attrs['command']],
            args    = args
        )
        
        letters     = string.ascii_lowercase
        rand_suffix = ''.join(random.choice(letters) for i in range(5))
        job_name    = f"{exp['k8s_job']}-{rand_suffix}"

        if 'additional-labels' in job_attrs:
            logging.info(f"additional-labels = {job_attrs['additional-labels']}")
            pod_template = create_pod_template(f"{exp['k8s_job']}_exec", job_attrs['additional-labels'], container, exp['name'], codename)
        else:
            pod_template = create_pod_template(f"{exp['k8s_job']}_exec", {}, container, exp['k8s_job'], codename)
        
        logging.info(f"Creating job {job_name}")
        job_def = create_job(job_name, pod_template, codename)

        try:
            batch_api.create_namespaced_job(namespace, job_def)
            logging.info(f"Job {job_name} created successfully")

        except ApiException as e:
            logging.info(f"Error creating job: {e}")
            quit()

        metric_job_name = job_name.replace("-","_")
        r.set(f"chaos_jobs_status:{codename}:{exp['name']}:{metric_job_name}", 0.0)
        
        if r.exists('chaos_node_jobs_total') == 1:
            r.incr('chaos_node_jobs_total')
        else:
            r.set("chaos_node_jobs_total", 1)

if __name__ == "__main__":
    logging.basicConfig(
        level  = os.environ.get("LOGLEVEL", "INFO"),
        format = "%(asctime)s [PROGRAMMING_MODE] %(message)s"
    )
    logging.info('Starting script...')

    if os.path.exists(sys.argv[1]) == False:
        logging.error("Chaos program not found, please check the path...")
        exit(1)

    parsed_yaml = parse_yaml()

    r = redis.Redis(unix_socket_path='/tmp/redis.sock')

    token = os.environ["TOKEN"]

    configuration = client.Configuration()
    configuration.api_key = {"authorization": f"Bearer {token}"}
    configuration.host = sys.argv[2]

    configuration.insecure_skip_tls_verify = True
    configuration.verify_ssl = False

    client.Configuration.set_default(configuration)
    client.Configuration.set_default(configuration)

    api_instance = client.CoreV1Api()
    batch_api    = client.BatchV1Api()

    k8s_regex  = "[a-z0-9]([-a-z0-9]*[a-z0-9])?"

    for job in parsed_yaml["k8s_jobs"]:
        logging.info(f"Found job {job}")
        if not re.fullmatch(k8s_regex, job):
            ret = f"Invalid name for k8s_jobs: {job}, please match Kubernetes name format '[a-z0-9]([-a-z0-9]*[a-z0-9])?'"
            logging.info(ret)
            quit()
        
    for exp in parsed_yaml["experiments"]:
        perform_experiment(exp, parsed_yaml)

    os.remove(sys.argv[1])
