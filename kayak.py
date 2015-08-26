# coding=utf-8
import json
import time
import threading
import signal
import sys
import logging
import os
from kazoo.client import KazooClient
from autobahn.twisted.websocket import WebSocketServerProtocol, WebSocketServerFactory
from twisted.internet import reactor
sys.path.insert(0, "/pykafka")
from pykafka import KafkaClient
import pykafka.protocol

def get_brokers():
	print "ZK", os.environ['ZOOKEEPER']
	zk = KazooClient(hosts=os.environ['ZOOKEEPER'], read_only=True)
	zk.start()

	broker_list = ""
	children = zk.get_children( '/brokers/ids' )
	for i in children:
		data, stat = zk.get( '/brokers/ids/'+i )
		data = json.loads( data )
		if broker_list != "":
			broker_list += ","
		broker_list += data['host'].encode('utf8') + ":" + str(data['port'])

	data, stat = zk.get( '/brokers/ids/0' )
	zk.stop()
	data = json.loads( data )
	return broker_list

def setup_logging():
	root = logging.getLogger()
	root.setLevel(logging.INFO)
	ch = logging.StreamHandler(sys.stdout)
	ch.setLevel(logging.INFO)
	formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
	ch.setFormatter(formatter)
	root.addHandler(ch)

consumer_group_id = "kayak"

setup_logging()
brokers = get_brokers()

kafka = KafkaClient( hosts=brokers )

class KafkaThread(threading.Thread):
	def __init__(self, args):
		print "CREATE THREAD", brokers
		super(KafkaThread, self).__init__(args=args)
		self.stop_request = False
		self.topic_id = args[1].encode('utf8')
		self.protocol = args[0]

		self.inside_thread_kafka = KafkaClient( hosts=brokers )

		print "setup topic "+self.topic_id
		self.topic = self.inside_thread_kafka.topics[self.topic_id]
		self.consumer_group_id = consumer_group_id
		print "create consumer group", self.consumer_group_id
		self.consumer = self.topic.get_simple_consumer( self.consumer_group_id )

		print "reset offsets"
		# ACB: pykafka fails miserably if you try to reset offsets to head and there is no offset
		offsets = list(set([ res.offset[0] for p, res in self.topic.latest_available_offsets().items() ]))
		if not (len(offsets) == 1 and offsets[0] == -1):
			# SKIP all data up to now.
			self.consumer.reset_offsets( [ (v, -1) for k,v in self.topic.partitions.items() ] )
		print "done"


	def run(self):
		print "THREAD RUN"
		while not self.stop_request:
			try:
				message = self.consumer.consume(block=False)
					# I have to block=False here because otherwise when the websocket
					# terminates and there are no more messages on the consumer then
					# this thread will never die. There is no block_for_at_most type
					# argument to the consume.
				if message:
					ret_message = {
						'topic': self.topic_id,
						'message': json.loads(message.value)
					}
					self.protocol.sendMessage( json.dumps(ret_message) )
				else:
					time.sleep( 0.1 )
			except Exception as e:
				print "SLEEP ON EXECPTION", e
				time.sleep(0.1)

		print "THREAD STOPPED"

	def stop(self):
		print "THREAD STOP REQUEST"
		self.stop_request = True

class MyServerProtocol(WebSocketServerProtocol):
	def __init__(self):
		print "ON INIT"
		self.kafka_threads = {}

	def send( self, obj ):
		self.sendMessage( json.dumps( obj ) )

	def subscribe(self,topic_id):
		self.kafka_threads[topic_id] = KafkaThread( args=(self,topic_id) )
		self.kafka_threads[topic_id].start()

	def unsubscribe(self,topic_id):
		self.kafka_threads[topic_id].stop()

	def history(self,topic_id,offset,count):
		topic = kafka.topics[topic_id]
		consumer = topic.get_simple_consumer( consumer_group_id )
		consumer.seek(offset,1)
		while True:
			message = consumer.consume(block=False)
			if message:
				self.sendMessage(message.value)
			else:
				break

	def onConnect(self, request):
		print "ON CONNECT", request

	def onOpen(self):
		print "ON OPEN"
		self.path = self.http_request_path
		self.query = self.http_request_params

	def onMessage(self, payload, isBinary):
		try:
			print "Got Message"
			comm = json.loads(payload)
			handled = False
			if "command" in comm:
				print "Command=", comm["command"]
			if 'topic' in comm:
				topic_id = comm["topic"].encode("utf8")
			if comm["command"] == "ping":
				handled = True
			if comm["command"] == "subscribe":
				self.subscribe( topic_id )
				handled = True
			if comm["command"] == "unsubscribe":
				self.unsubscribe( topic_id )
				handled = True
			if comm["command"] == "history":
				self.history( topic_id, comm["offset"], comm["count"] )
				handled = True
			if comm["command"] == "add":
				topic = kafka.topics[topic_id]
				producer = topic.get_producer()
				producer.produce( [ json.dumps(comm["message"]) ] )
				handled = True

			if not handled:
				self.send( {'error':'command not understood'} )
		except Exception as e:
			self.send( {'error':str(e)} )

	def onClose(self, wasClean, code, reason):
		print "ON CLOSE", wasClean, code, reason
		for topic_id,thread in self.kafka_threads.items():
			thread.stop()

if __name__ == '__main__':
	headers = {
		"Access-Control-Allow-Origin": "*"
	}
	factory = WebSocketServerFactory("ws://*:80",debug=True,headers=headers)
	factory.protocol = MyServerProtocol
	reactor.listenTCP(80,factory)
	print "Listening on 80"

	reactor.run()
	print "ENDED"
