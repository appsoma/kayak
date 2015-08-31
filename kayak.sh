#!/usr/bin/env bash

[ -z "$ZK_HOST_LIST" ] && echo "You must have ZK_HOST_LIST env var set" && exit 1;

# 	"cmd": "cd /reactor_core/extern_code; python -u ./pywelder/kayak.py > ${WELDER_LOG}",
# ; bash -c \"echo hello > $WELDER_LOG\"
#	"healthChecks": [
#		{
#			"path": "/",
#			"protocol": "HTTP",
#			"portIndex": 0,
#			"gracePeriodSeconds": 300,
#			"intervalSeconds": 10,
#			"timeoutSeconds": 20,
#			"maxConsecutiveFailures": 3
#		}
#	],

if [ "$1" == "stop" ] || [ "$1" == "restart" ]; then
	curl -H "Content-Type:application/json" -X DELETE http://localhost:8080/v2/apps/kayak
fi

if [ "$1" == "start" ] || [ "$1" == "restart" ]; then

cat >/tmp/kayak_run.json <<EOL
{
	"id": "/kayak",
	"cmd": "cd /kayak; umask u=rwx,g=rwx,o=r; python -u ./kayak.py >> \$WELDER_LOG 2>&1",
	"cpus": 0.1,
	"mem": 100.0,
	"instances": 1,
	"env": {
		"ZOOKEEPER": "${ZK_HOST_LIST}",
		"HAPROXY_HTTP": "0",
		"WELDER_LOG": "/mnt/data/logs/kayak.log"
	},
	"container": {
		"type": "DOCKER",
		"docker": {
			"image": "zsimpson/kafka_autobahn:latest",
			"network": "BRIDGE",
			"portMappings": [
				{
					"containerPort": 80,
					"hostPort": 0,
					"protocol": "tcp"
				}
			]
		},
		"volumes": [
			{
				"hostPath": "/mnt/data/kayak",
				"containerPath": "/kayak",
				"mode": "RO"
			},
			{
				"hostPath": "/mnt/data/pykafka",
				"containerPath": "/pykafka",
				"mode": "RO"
			},
			{
				"hostPath": "/mnt/data/logs",
				"containerPath": "/mnt/data/logs",
				"mode": "RW"
			}
		]
	}
}
EOL
# Note, I use localhost and the port here so that this code will be generic between then dev and stable clusters
curl -H "Content-Type:application/json" -X POST --data @/tmp/kayak_run.json http://localhost:8080/v2/apps

fi