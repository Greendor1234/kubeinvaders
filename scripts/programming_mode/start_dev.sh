#! /bin/bash

secret=$(kubectl get secret -n kubeinvaders | grep 'service-account-token' | awk '{ print $1}')
token=$(kubectl describe secret $secret -n kubeinvaders | grep 'token:' | awk '{ print $2}')
ip=$(ip address show eth0 | grep inet | grep -v inet6 | awk '{ print $2 }' | awk -F/ '{ print $1 }')
export TOKEN=$token
python3 start.py experiments.yaml https://${KUBERNETES_SERVICE_HOST}:${KUBERNETES_SERVICE_PORT_HTTPS}
