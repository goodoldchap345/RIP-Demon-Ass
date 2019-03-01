import struct
import socket
import sys
import select
import configparser
import time
import random

'''
The following is an example of my configuration files, to assist with understanding the format

------------------------------------------

[RIP_Demon_Parameters]

routerID = "1"
inputPorts = "6110,6201,7345"
outputs = "5000-1-1, 5002-5-4"
timerValues = "180,30"

'''

'''
RIP packages will contain the RIP header and the routing table as a 2D list. Each entry in the
2D list will be a list containing information about 1 router, with the following format:
[routerID, address,first router to destination, metric, time since last update]
Each contact will be packed into a long using the struct module.
'''

def convertOutput(outputs):#function which converts output router information from [xxxx-x-x,xxxx-x-x,xxxx-x-x] in string format to 2D list [[port of the pair router, metric value of link to the router, router id of the router]x3] in integer format
    outputData = []#creates an empty list which will contain data on all peer output routers.
    
    for output in outputs:
        outputInfo = output.split("-")
        outputInfo = [int(j) for j in outputInfo]
        outputData.append(outputInfo)

    return outputData#return a list of output routers, which are each represented by a list containing their port number, metric value and router id

def performConfigTests(routerID, inputPorts, outputs, timeoutValue, periodicValue):#function which tests the data from the config file

    if "\n" in inputPorts:#performs check that all input ports are in one line
        print("Config data invalid, ports not in one line. Ending program")
        return

    inputPorts = inputPorts.split()#split inputPorts from string to list of strings
    for i in range(0, len(inputPorts)):
        inputPorts[i] = int(inputPorts[i])

    if "\n" in outputs:
        print("Config data invalid, ports not in one line. Ending program")
        return
    outputData = convertOutput(outputs)

    if ((routerID < 1) or (routerID > 64000)):#if ID outside of valid range
        return False

    usedPortNumbers = []#creates a list to check if an input port number has already been used

    for inputPortNumber in inputPorts:#for each port number in the list
        if ((inputPortNumber < 1024) or (inputPortNumber > 64000)):#if the number is outside of the range
            return False
        elif (inputPortNumber in usedPortNumbers):#if the port number has already been used
            return False
        else:
            usedPortNumbers.append(inputPortNumber)#if not, add the port number

    for outputPortData in outputData:#for each output port data entry
        if((outputPortData[0] < 1024) or (outputPortdata[0] > 64000)):#if the output port number is out of range
            return False
        elif(outputPortData[0] in usedPortNumbers):#if the port number s already used
            return False
        elif (outputPortData[1] > 15):#if the output metric number is greater than "infinity"
            return False
        else:
            usedPortNumbers.append(outputPortData[0])

    if (timeoutValue/periodicValue != 6):#if timeout ratio is incorrect
        return False

    if (routerID == [] or inputPorts == [] or outputData == []):#if information is missing from the config file
        return False

    return True#return true if all tests are passed

def performPacketChecks(packetReceived, routerID):
    command = struct.unpack_from(">B", packetReceived, 0)#unpack the header info
    version = struct.unpack_from(">B", packetReceived, 1)
    receivedRouterID = struct.unpack_from(">H", packetReceived, 2)
    firstCompulsoryZero = struct.unpack_from(">H", packetReceived, 6)
    secondCompulsoryZero = struct.unpack_from(">L", packetReceived, 12)
    thirdCompulsoryZero = struct.unpack_from(">L", packetReceived, 16)
    metric = struct.unpack_from(">L", packetReceived, 20)


    if (command != 2):#if it is not a response packet
        return False
    if (version != 2):#if it is not version 2
        return False
    if (routerID == receivedRouterID):#if the router ID is the same as the host router
        return False
    if ((firstCompulsoryZero + secondCompulsoryZero + thirdCompulsoryZero) != 0):#if the sum of the zero fields does not = 0, then at least one of them isn't 0
        return False
    if (metric >= 16):#if the metric is too high
        return False

    return True#if none of these cases are true, return true

def createRoutingTable(outputData):#initialises the routing table for the router with output data from config files
    #[port of the pair router, metric value of link to the router, router id of the router] converts to
    #routerID, address,first router to destination, metric, time of last update
    routingTable = []#initialise routing table
    routingCount = 0
    for outputRouter in outputData:#for each router in the outputData
        routerData = [outputRouter[2], outputRouter[0], outputRouter[2], outputRouter[1], time.time()]#the entry into the routing table will be as follows for the initial neighbours
        routingTable[routingCount] = routerData#insert the router into the routertable
        routingCount = routingCount + 1

    return routingTable

def findMetric(routerID, routingTable):#return the metric of a router given the ID using the routing table
    for router in routingTable:
        if (routerID == router[0]):
            return router[3]
        else:
            return

def composeResponse(routingTable, routerID, recipient):#composes packet to send

    routerResponse = bytearray(512)

    command = 2
    version = 2
    mustBeZero = 0

    for destination in routerResponse:
        if (destination[2] == recipient):#if the first hop is the recipient of the response, then split horizons are needed
            destination[1] = 16#metric becomes infinity to adhere with poisoned reverse split horizon (which by the way sounds like a dragonballZ move)

    struct.pack_into(">B", routerResponse, 0, command)
    struct.pack_into(">B", routerResponse, 1, version)
    struct.pack_into(">H", routerResponse, 2, routerID)
    struct.pack_into(">H", routerResponse, 6, mustBeZero)
    struct.pack_into(">H", routerResponse, 12, mustBeZero)
    struct.pack_into(">H", routerResponse, 16, mustBeZero)

    count = 0

    while (count < len(routingTable)):
        struct.pack_into(">L", routerResponse, 20 + count * 4, routingTable[count])
#errormarker
    return routerResponse

def updateRoutingTable(packetReceived, routingTable):#updates routing table according to the new packet received
    receivedRouterID = struct.unpack_from(">H", packetReceived, 2)
    newRouterCount = struct.unpack_from(">B", packetReceived, 24)#unpack the number of routers in the list. At this point I'm making 1 Long = 1 router profile
    receivedTable = []#initialise received router table
    routersAddedCount = 0#initialise counter for routers added so far
    while (newRouterCount > 0):#unpack the received routing table one long at a time. One routing destination is packed into one long
        newRouterCount = newRouterCount - 1
        receivedTable[routersAddedCount] = struct.unpack_from(">L", packedReceived, 25 + routersAddedCount)
        routersAddedCount = routersAddedCount + 1
    #WATCH THIS SPOT HERE AND CONFIRM IF IT WORKS *MARKER*

    for destination in receivedTable:#for each item in new routing table

        existingCount = 0#initiate count of existing routers checked so far for this destination in received routing table
        alreadyExisted = 0#create variable to track if a router was already in local routing table

        for existingDestination in routingTable:#for each item in existing table

            if (destination[0] == existingDestination[0]):#if the router numbers are the same in each table, compare information

                alreadyExisted = 1
                if (findMetric(existingDestination[0], routingTable) > findMetric(receivedRouterID, routingTable) + findMetric(destination[0], receivedTable)):#if the old metric is greater than new metric + metric to router

                    routingTable[existingCount][2] = receivedRouterID#set first hop to the id of the router we received the update from
                    routingTable[existingCount][3] = findMetric(receivedRouterID, routingTable) + findMetric(destination[0], receivedTable)#set new metric to the metric of the hop to the first hop router + metric of that router to destination
                    routingTable[existingCount][4] = time.time()#reset timer since entry was last updated

            existingCount = existingCount + 1#increment the number of existing routers checked

        if (alreadyExisted == 0):#if after iterating through every existing destination in routing table the new router id was not found
            newDestination = [destination[0], destination[1], receivedRouterID, findMetric(receivedRouterID, routingTable)+findMetric(destination[0], receivedTable),0]#create new router profile and append to existing table
            routingTable.append(newDestination)

    return routingTable

def main():
    configurationFile = str(sys.argv[1])#take the file path and name of the config file from the command line
    configParser = configparser.RawConfigParser()#set up the configuration parser to read config files
    configParser.read(configurationFile)#read the file

    routerID = configParser.get('RIP_Demon_Parameters', 'routerID')#Assigns local integer routerID to
    #be the integer value of routerID in the config file with header [RIP_Demon_Parameters]
    routerID = int(routerID)
    
    inputPorts = (configParser.get('RIP_Demon_Parameters', 'inputPorts'))#assigns inputPorts to be a list of strings of
    #the port numbers
    inputPorts = inputPorts.split(",")

    outputs = configParser.get('RIP_Demon_Parameters', 'outputs').split(",")#assigns outputs to be a list of the output values as strings.

    timeoutValue = configParser.get('RIP_Demon_Parameters', 'timeoutValue')
    periodicValue = configParser.get('RIP_Demon_Parameters', 'periodicValue')
    timeoutValue = int(timeoutValue)
    periodicValue = int(periodicValue)
    
    inputPorts = [int(j) for j in inputPorts]
    outputData = convertOutput(outputs)

    if (performConfigTests(routerID, inputPorts, outputs, timeoutValue, periodicValue) == False):
        print("Configuration file invalid, ending program")
        return

    socketList = []#create an empty list where I can dynamically create and bind sockets. This is needed as I do not know the number of ports I need to bind to and must create socket from an unknown size list.

    inputCount = 0 #initialise count of input ports for naming purposes
    for inputPort in inputPorts:#for each input port number I have
        socketList[inputCount] = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)#create another socket
        socketList[inputCount].bind(socket.gethostname(), inputPort)#bind the socket with the port number
        socketList[inputCount].listen()#begin listening to the socket
        inputCount = inputCount + 1#increment to create next socket with next port number

    routingTable = createRoutingTable(outputData)#format routerID, address,first router to destination, metric, time since last update
    #Each destination will also be a list, so this will be a 2D list

    timeSincePeriodicResponse = time.time()#initialise time

    while(1):
        #This loop needs to constantly monitor for incoming messages and update internal routing table accordingly, as well as sending out schedulued messages containing its internal routing table to its neighbours. Also, needs to handle neighbour shutdowns after timeout

        #need to create random offset for time waited but it's bugging out##errormarker

        if (time.time() >= timeSincePeriodicResponse + periodicValue/10 * random.randint(8,12)):#if the periodic value of time has passed
            timeSincePeriodicResponse = time.time()#set time since response to be current time
            routerResponse = composeResponse(routingTable, routerID)#compose the response packet
            for neighbouringRouter in outputData:#for each neighbour
                socketList[0].sendto(routerResponse, (socketList[0].gethostname(), neighbouringRouter[0]))#use a socket to send the update
        #above can be made into a function later

        routesChecked = 0
        for route in routingTable:#for each route in the table
            if (time.time() - route[4] > timeoutValue):#if the time elapsed passed the timeout value
                routingTable[routesChecked] = None#check if none will bug out #errormarker
                #send triggered update
                for neighbouringRouter in outputData:#for each neighbour
                    routerResponse = composeResponse(routingTable, routerID, neighbouringRouter)#compose the response packet
                    socketList[0].sendto(routerResponse, (socketList[0].gethostname(), neighbouringRouter[0]))#use a socket to send the update

        #errormarker i think below here for loop isn't needed, use select to listen simultaneously

        for inputSocket in socketList:#for every socket created
            readable, writeable, exceptional = select.select(inputs, outputs, inputs)#initialise select
            socketReady = select.select(([inputSocket], [], []))#assign boolean of whether or not input socket is ready

            if socketReady[0]:#if something is receivable from this port number
                packetReceived = inputSocket.recvfrom(4096)#recive it and assign it to packetReceived
                #now we need to process it-check validity of incoming package, update routing table
                if (performPacketChecks(packetReceived, routerID) == False):#if test failed
                    continue#ignore this packet
                else:
                    routingTable = updateRoutingTable(packetReceived, routingTable)#update routing table


main()
