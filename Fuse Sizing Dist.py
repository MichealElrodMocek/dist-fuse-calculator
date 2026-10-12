import math
import cmath
import numpy

#inputs
V_ll = 12470 #volts
tapLineResistivity = complex(1.32, .65) #ohm per mile
feederLineResistivity = complex(1.32, .65) #ohm per mile
feederLengthMi = 2.5 #miles
i3phFault = 4500 #amps
iGroundFault = 3500 #amps
transformerSizes = [25, 50, 75] #KVA

V_ph = V_ll / math.sqrt(3)

Z1tap = V_ph / i3phFault
Z2tap = Z1tap
Z0tap = 3 * V_ph / iGroundFault - (Z1tap + Z2tap)

Z1lat = 
Z2lat = 
Z0lat = 

Zf = 0 # we will assume a bolted fault and neglect arc resistance and ground resistance



parent = ['8T', '10T', '12T', '15T', '20T', '25T', '30T', '40T', '50T', '65T', '80T', '100T', '140T', '200T']
child = ['6T', '8T', '10T', '12T', '15T', '20T', '25T', '30T', '40T', '50T', '65T', '80T', '100T', '140T']

row0  = [225, 360, 550, 780, 1050, 1400, 1750, 2250, 2900, 3600, 4550, 5900, 7100,  10000, 10000]
row1  = [0,   140, 400, 690, 990,  1350, 1750, 2250, 2900, 3600, 4550, 5900, 7100,  10000, 10000]
row2  = [0,   0,   220, 560, 900,  1300, 1650, 2250, 2900, 3600, 4550, 5900, 7100,  10000, 10000]
row3  = [0,   0,   0,   300, 710,  1200, 1600, 2200, 2800, 3600, 4550, 5900, 7100,  10000, 10000]
row4  = [0,   0,   0,   0,   400,  910,  1450, 2000, 2700, 3500, 4550, 5900, 7100,  10000, 10000]
row5  = [0,   0,   0,   0,   0,    0,    1200, 1800, 2550, 3400, 4500, 5900, 7100,  10000, 10000]
row6  = [0,   0,   0,   0,   0,    0,    0,    1500, 2350, 3200, 4300, 5500, 7000,  10000, 10000]
row7  = [0,   0,   0,   0,   0,    0,    0,    0,    1950, 3000, 4050, 5400, 7000,  10000, 10000]
row8  = [0,   0,   0,   0,   0,    0,    0,    0,    0,    2500, 3700, 5050, 6900,  10000, 10000]
row9  = [0,   0,   0,   0,   0,    0,    0,    0,    0,    0,    3000, 4500, 6400,  10000, 10000]
row10 = [0,   0,   0,   0,   0,    0,    0,    0,    0,    0,    0,    3700, 5900,  10000, 10000]
row11 = [0,   0,   0,   0,   0,    0,    0,    0,    0,    0,    0,    0,    4700,  9600,  10000]
row12 = [0,   0,   0,   0,   0,    0,    0,    0,    0,    0,    0,    0,    0,     8800,  10000]
row13 = [0,   0,   0,   0,   0,    0,    0,    0,    0,    0,    0,    0,    0,     6000,  10000]
row14 = [0,   0,   0,   0,   0,    0,    0,    0,    0,    0,    0,    0,    0,     0,     10000]
faultTable = [row1, row2, row3, row4, row5, row6, row7, row8, row9, row10, row11, row12, row13]

tSizes = [1, 2, 3, 6, 8, 10, 12, 15, 20, 25, 30, 40, 50, 65, 80, 100, 140]

V_ph_kV = V_ph / 1000
transformerCurrent = numpy.zeros(3)
transformerFuseSize = transformerCurrent
for a in range(len(transformerSizes)):
    transformerCurrent[a] = transformerSizes[a] / V_ph_kV
    
for a in range(len(transformerFuseSize)):
    for b in range(len(tSizes)):
        if transformerCurrent[a] < tSizes[b]:
            transformerFuseSize[a] = tSizes[b]
            break

