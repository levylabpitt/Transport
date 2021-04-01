import zmq
import time
from datetime import datetime
import sys

print(f'Starting server...')

# Provide port as command line argument to run server at two different ports.
port = "5556"
if len(sys.argv) > 1:
    port =  sys.argv[1]
    int(port)
	
print(port)

# Server is created with a socket type “zmq.REP” and is bound to well known port.
context = zmq.Context()
socket = context.socket(zmq.REP)
socket.bind(f'tcp://*:{port}')

'''
while True:
    #  Wait for next request from client
    message = socket.recv()
    print("Received request: ", message)
    time.sleep(1)  
    socket.send_string("World from %s" % port)
'''
	
while True:
	#  Wait for next request from client
	message = socket.recv()
	print(f'Received request: {message}')
	
	#  Do some 'work'
	time.sleep(1)
	
	#  Send reply back to client
	now = datetime.now()
	current_time = now.strftime("%H:%M:%S")
	send_message = f'Hello the time is {current_time}'
	socket.send(bytearray(send_message, 'utf-8'))