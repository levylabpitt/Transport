import zmq
import json
import numpy as np

# open socket for TCP communication
context = zmq.Context()
socket = context.socket(zmq.REP)
socket.bind("tcp://127.0.0.1:15213")

while True:
    #  Wait for request from client
    message = socket.recv()
    print("Received request: %s" % message)
    try:
        #r = eval(message)
        print("Return value: ", message)
        print("Type: ", type(message))
        #socket.send(bytearray(json.dumps(r, cls=NumpyEncoder), 'utf-8'))
        socket.send(bytearray(str(message),'utf-8'))
    except NameError:
        print("except NameError")
        socket.send(b"Unknown command")
    except SyntaxError:
        print("except SyntaxError")
        socket.send(b"Invalid syntax")
    except:
        print("except")
        socket.send(b"Unknown error")
