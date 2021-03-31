import time
import zmq

#ZMQ setup
context = zmq.Context()
socket = context.socket(zmq.REQ)
socket.bind("tcp://127.0.0.1:15213")

#Experiment setup
temperatures = [300,350,400]
experiments = ["Command: Wait", "Command: Lockin_Vsg"]
command_list = ""

for y in temperatures:
    command = "Command: Set Temperature >> {}".format(y)
    command_list = command_list + command + ',\n'
    # print(command)
    for magnet in range(-9,9):
        command = "Command: Set Magnet >> {}".format(magnet)
        # print(command)
        command_list = command_list + command + ',\n'
        for x in experiments:
            # time.sleep(0.01)
            command = x.format(y)
            # print(command)
            command_list = command_list + command + ',\n'

print(command_list)

# Send commands as a single csv string to REP socket (LabVIEW will parse the string)
socket.send_string(command_list)




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

