import time
import zmq
import sys

#ZMQ setup
context = zmq.Context()
socket = context.socket(zmq.REQ)
socket.connect("tcp://localhost:15213")

#Experiment setup
temperatures = [300,325,350]
experiments = ["Wait >> 1000", "Lockin_Vsg"]
command_list = ""


for y in temperatures:
    command = "Set Temperature >> {}".format(y)
    command_list = command_list + command + ',\n'
    # print(command)
    for magnet in range(-1,2):
        command = "Set Magnet >> {}".format(magnet)
        # print(command)
        command_list = command_list + command + ',\n'
        for x in experiments:
            # time.sleep(0.01)
            command = x.format(y)
            # print(command)
            command_list = command_list + command + ',\n'

print(command_list)
socket.send_string(command_list)
reply = socket.recv_string()
print(f"server replied: {reply}")

# Send commands as a single csv string to REP socket (LabVIEW will parse the string)
# To do: format as JSON RPC
'''
while True:
    socket.send_string("Get Status")
    status = socket.recv_string()
    print(status)
    if status.find("busy") != -1:
        time.sleep(1)
        continue
    else:
        break
'''
'''
for i in range(10):
    data = f"Wait >> {i*500}"
    socket.send_string(data)
    print(f"Sending: {data}")
    reply = socket.recv_string()
    print(f"Server replied: {reply}")
'''
#socket.send_multipart(command_list)

sys.exit()

'''
Mark Code:

import itertools as it

temps = [300, 350, 400]
mags  = range(-9, 9)
tm_cross_product = it.product(temps, mags) # set wise cross-product of elements "all against all"

print("\n".join("{} \t {}".format(*tm) for tm in tm_cross_product))
command_template = "Set Temperature >> {}\nSet Magnet >> {}\nWait\nLockin Vsg\n"
print("\n".join(command_template.format(*tm) for tm in tm_cross_product))

'''

