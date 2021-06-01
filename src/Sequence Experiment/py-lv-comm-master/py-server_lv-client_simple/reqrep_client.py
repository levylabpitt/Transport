import zmq
import sys

# play with zmq stuff

version = zmq.pyzmq_version()
print(f'pyzmq version = {version}')

# Provide two ports of two different servers to connect to simultaneously.

port = "5556"
if len(sys.argv) > 1:
    port1 =  sys.argv[1]
    int(port1)

if len(sys.argv) > 2:
    port2 =  sys.argv[2]
    int(port2)

# Client is created with a socket type “zmq.REQ”.
# You should notice that the same socket can connect to two different servers.
# connect socket
context = zmq.Context()
print(f'Connecting to server...')
socket = context.socket(zmq.REQ)

socket.connect(f'tcp://localhost:{port1}')
print(f'Connected to Server tcp://localhost:{port1}') 

if len(sys.argv) > 2:
	print(f'Connected to tcp://localhost: {port2}')
	socket.connect(f'tcp://localhost:{port2}')


# You have to send a request and then wait for reply.
# Do 10 requests, waiting each time for a response
for request in range(10):
	print(f'\nSending request {request}')
	socket.send(b"Hello")
    #  Get the reply.
	message = socket.recv()
	print(f'Received reply {request} [ {message} ]')
	print(f'Message type: {type(message)}')
	print(f'Decoded message: {message.decode()}')
	print(f'Decoded message type: {type(message.decode())}')

# disconnect socket
socket.disconnect(f'tcp://localhost:{port1}')
print(f'Disconnected from Server tcp://localhost:{port1}')

if len(sys.argv) > 2:
	print(f'Disconnected from tcp://localhost:{port2}')
	socket.connect(f'tcp://localhost:{port2}')
