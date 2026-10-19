import math
import cmath
import numpy as np
import warnings

# typed inputs
V_ll = 12470 #volts
feederLengthFt = 20000 #fr
gmr_phase = .1 #given
soilResistivity = 100 #ohm-meters
D_an = 4.0 # Distance in feet between closest phase conductor and neutral
S_sc = 500 * 1e6 #VA
x_over_r = 10 #taken from nameplate of substation transformer
            
#drop down inputs
condTemp = [25, 50, 75] #deg C
priSizeChoice = 2
neutSizeChoice = 2
latPriSizeChoice = 2
condTemp = 2

# Taken from one-line
latLoadA = 750 #KVA
latLoadB = 750
latLoadC = 750
latLoadVec = [latLoadA, latLoadB, latLoadC]

latLargestXFMR_A = 75
latLargestXFMR_B = 75
latLargestXFMR_C = 75
latLargestXFMR_Vec = [latLargestXFMR_A, latLargestXFMR_B, latLargestXFMR_C]
            
#assumptions
freq = 60 #Hz

#tables
condSize = ['4', '2', '1/0', '2/0', '4/0', '336.4', '477', '556.5']
rad_inch = [.204, .258, .325, .365, .410, .460]
gmr_inch = [.0524, .0502, .0535, .0612, .0977, .2928, .4296, .4620]

# AC Resistance vectors (ohm/kft) for 25°C, 50°C, and 75°C
r_25 = np.array([0.412, 0.259, 0.163, 0.130, 0.0822, 0.0523, 0.0369, 0.0318])
r_50 = np.array([0.479, 0.308, 0.197, 0.162, 0.107, 0.0574, 0.0405, 0.0348])
r_75 = np.array([0.522, 0.336, 0.216, 0.176, 0.116, 0.0625, 0.0441, 0.0379])

# Inductive Reactance vectors (ohm/kft) for 25°C, 50°C, and 75°C
x_25 = np.array([0.115, 0.128, 0.116, 0.112, 0.0964, 0.0826, 0.0835, 0.0818])
x_50 = np.array([0.137, 0.123, 0.104, 0.113, 0.105, 0.0826, 0.0835, 0.0818])
x_75 = np.array([0.131, 0.110, 0.114, 0.102, 0.105, 0.0826, 0.0835, 0.0818])

#now, let's convert everything to ohm/mile
for a in range(len(r_25)):
    x_25[a] = x_25[a] * 5280 / 1000
    x_50[a] = x_50[a] * 5280 / 1000
    x_75[a] = x_75[a] * 5280 / 1000
    r_25[a] = r_25[a] * 5280 / 1000
    r_50[a] = r_50[a] * 5280 / 1000
    r_75[a] = r_75[a] * 5280 / 1000      

r_allTemp = [r_25, r_50, r_75]
x_allTemp = [x_25, x_50, x_75]

# Max Ampacity vector (Amperes)
ampacity = np.array([140, 185, 240, 275, 365, 515, 640, 710])
maxFuseForLat = np.array([140, 200, 200, 200, 200, 200, 200, 200])

parent = [6, 8, 10, 12, 15, 20, 25, 30, 40, 50, 65, 80, 100, 140, 200]
child = ['1T', '2T', '3T', '6T', '8T', '10T', '12T', '15T', '20T', '25T', '30T', '40T', '50T', '65T', '80T', '100T', '140T']

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
faultTable = [row0, row0, row0, row1, row2, row3, row4, row5, row6, row7, row8, row9, row10, row11, row12, row13]

tSizes = [1, 2, 3, 6, 8, 10, 12, 15, 20, 25, 30, 40, 50, 65, 80, 100, 140, 200]

# calculations
V_ph = V_ll / math.sqrt(3)

r_phase = r_allTemp[condTemp][priSizeChoice]
r_neutral = r_allTemp[condTemp][neutSizeChoice]
priResistiv = complex(r_phase, x_allTemp[condTemp][priSizeChoice])
neutResistiv = complex(r_neutral, x_allTemp[condTemp][neutSizeChoice])

# substation data
Z_base = (V_ll ** 2) / S_sc

# calculate R and X using pythagorean theorem
R_s = Z_base / math.sqrt((x_over_r ** 2) + 1)
X_s = math.sqrt((Z_base ** 2) - (R_s ** 2))

# we assume that the source is balanced
Z_source_pos = complex(R_s, X_s)
Z_source_zero = Z_source_pos
                      
# Radius in feet
rad_feet = np.zeros(len(rad_inch))
gmr_feet = rad_feet
for a in range(len(rad_feet)):
    rad_feet[a] = rad_inch[a] / 12
    gmr_feet[a] = gmr_inch[a] / 12
                      
rad_pri_feet = rad_feet[priSizeChoice]
rad_neut_feet = rad_feet[neutSizeChoice]
gmr_pri_feet = gmr_feet[priSizeChoice]
gmr_neut_feet = gmr_feet[neutSizeChoice]

# 1. Calculate Earth return terms
# Earth resistance per mile at given frequency
r_e = 0.001588 * freq

# Equivalent depth of earth return (feet)
D_e = 2160 * math.sqrt(soilResistivity / freq)

# kron reduction 
z_aa = complex(r_phase + r_e, 0.1213 * math.log(D_e / gmr_pri_feet))
z_nn = complex(r_neutral + r_e, 0.1213 * math.log(D_e / gmr_neut_feet))
z_an = complex(r_e, 0.1213 * math.log(D_e / D_an))

z_ae = z_aa - (z_an ** 2) / z_nn

Z_line1 = priResistiv * feederLengthFt / 5280
Z_line0 = z_ae * feederLengthFt / 5280

Z1_total = Z_source_pos + Z_line1
Z2_total = Z1_total    # Z2 equals Z1 for static lines
Z0_total = Z_source_zero + Z_line0

Z_sum = Z1_total + Z2_total + Z0_total

I_012 = (3.0 * V_ph) / Z_sum

I_fLG_phasor = 3.0 * I_012
I_fLG_magnitude = abs(I_fLG_phasor)

# now, we calculate the largest transformer fuse
V_ph_kV = V_ph / 1000
transCurrent = max(latLargestXFMR_Vec) / V_ph_kV * 1.25

#calculate the smallest fuse size that doesn't trip the largest transformer at 125% loading
for a in range(len(tSizes)):
    if transCurrent < tSizes[a]:
        childFuse = tSizes[a]
        childFuseInd = a
        break

# now, with the child fuse and the fault current, we can calculate the fuse size
parentSizeInd = -5
for a in range(len(parent)):
    if faultTable[childFuseInd][a] > I_fLG_magnitude:
        parentSize = parent[a]
        parentSizeInd = a
        break
    
#we need to make sure this fuse can handle typical load
latCurrent = max(latLoadVec) / V_ph_kV

minLatFuseInd = -5
for a in range(len(tSizes)):
    if latCurrent < tSizes[a]:
        minLatFuse = tSizes[a]
        minLatFuseInd = a
        break

if parentSizeInd == -5:
    parentSize = 200
    warnings.warn("Fault Current too high. Defaulting to maximum 200T.")
elif minLatFuseInd == -5:
    parentSize = 200
    warnings.warn("Line Loading too high. Defaulting to maximum 200T.")
else:
    parentSize = max([parentSize, minLatFuse])

if ampacity[latPriSizeChoice] < parentSize:
    warnings.warn("Required Fuse size is too large for selected lateral primary. Defaulting to maximum fuse for chosen wire size")
    parentSize = maxFuseForLat[latPriSizeChoice]
