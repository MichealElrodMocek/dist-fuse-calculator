import math
import cmath
import numpy as np
import warnings


# typed inputs
V_ll = 12470 #volts
feederLengthFt = 20000 #fr
soilResistivity = 100 #ohm-meters
D_an = 4.0 # Distance in feet between closest phase conductor and neutral
S_sc = 500 * 1e6 #total fault power at substation transformer in VA
x_over_r = 10 #X/R ratio taken from nameplate of substation transformer
            
#drop down inputs
#NOTE: these inputs correspond to a selection index in a list, not a physical value

priSizeChoice = 2
neutSizeChoice = 2
latPriSizeChoice = 2
condTempChoice = 2

# Taken from one-line
latLoadA = 750 #KVA
latLoadB = 750
latLoadC = 750

latLargestXFMR_A = 75 #KVA
latLargestXFMR_B = 75
latLargestXFMR_C = 75

def feederTapCurrent(V_ll, feederLengthFt, soilResistivity, D_an, S_sc, x_over_r, priSizeChoice, priTypeChoice, neutSizeChoice, neutTypeChoice, latPriSizeChoice, latPriTypeChoice, condTempChoice, returnPhasor=False):

    #note: largestChildNonTX should be the largest child fuse calculated by the lateralLGFault function. If this fuse has no child fuses calculated this way, input should be 0
    
    #assumptions
    freq = 60 #Hz

    #tables
    condTempVec = [25, 50, 75] #deg C
                 
    condSize = ['4', '2', '1/0', '2/0', '4/0', '336.4', '477', '556.5']
    condType = ['ACSR', 'AAAC', 'AAC']

    # radius, gmr, resistance, and reactance for each onductor type and temperature combo
    rad_inch_acsr = np.array([0.1285, 0.1580, 0.1990, 0.2235, 0.2815, 0.3605, 0.4290, 0.4635])
    gmr_inch_acsr = np.array([0.0524, 0.0502, 0.0535, 0.0612, 0.0977, 0.2928, 0.4296, 0.4620])
    r_25_acsr = np.array([0.412, 0.259, 0.163, 0.130, 0.0822, 0.0523, 0.0369, 0.0318])
    r_50_acsr = np.array([0.479, 0.308, 0.197, 0.162, 0.1070, 0.0574, 0.0405, 0.0348])
    r_75_acsr = np.array([0.522, 0.336, 0.216, 0.176, 0.1160, 0.0625, 0.0441, 0.0379])
    x_25_acsr = np.array([0.115, 0.128, 0.116, 0.112, 0.0964, 0.0826, 0.0835, 0.0818])
    x_50_acsr = np.array([0.137, 0.123, 0.104, 0.113, 0.1050, 0.0826, 0.0835, 0.0818])
    x_75_acsr = np.array([0.131, 0.110, 0.114, 0.102, 0.1050, 0.0826, 0.0835, 0.0818])

    rad_inch_aaac = np.array([0.1250, 0.1580, 0.1990, 0.2235, 0.2815, 0.3600, 0.4290, 0.4635])
    gmr_inch_aaac = np.array([0.0908, 0.1147, 0.1445, 0.1623, 0.2044, 0.2729, 0.3252, 0.3513])
    r_25_aaac = np.array([0.4150, 0.2610, 0.1640, 0.1300, 0.0820, 0.0515, 0.0364, 0.0313])
    r_50_aaac = np.array([0.4510, 0.2840, 0.1780, 0.1410, 0.0891, 0.0560, 0.0396, 0.0340])
    r_75_aaac = np.array([0.4870, 0.3060, 0.1920, 0.1530, 0.0962, 0.0605, 0.0428, 0.0368])
    x_25_aaac = np.array([0.1120, 0.1066, 0.1013, 0.0987, 0.0934, 0.0867, 0.0827, 0.0809])
    x_50_aaac = x_25_aaac.copy()
    x_75_aaac = x_25_aaac.copy()

    rad_inch_aac = np.array([0.1160, 0.1460, 0.1840, 0.2070, 0.2610, 0.3330, 0.3975, 0.4290])
    gmr_inch_aac = np.array([0.0842, 0.1060, 0.1336, 0.1503, 0.1895, 0.2524, 0.3013, 0.3252])
    r_25_aac = np.array([0.4230, 0.2660, 0.1680, 0.1330, 0.0836, 0.0527, 0.0373, 0.0320])
    r_50_aac = np.array([0.4650, 0.2920, 0.1840, 0.1460, 0.0919, 0.0580, 0.0410, 0.0352])
    r_75_aac = np.array([0.5060, 0.3180, 0.2010, 0.1590, 0.1000, 0.0633, 0.0448, 0.0385])
    x_25_aac = np.array([0.1137, 0.1084, 0.1031, 0.1004, 0.0951, 0.0885, 0.0845, 0.0827])
    x_50_aac = x_25_aac.copy()
    x_75_aac = x_25_aac.copy()

    # combine the values into a matrix
    rad_inch_combined = np.array([rad_inch_acsr, rad_inch_aaac, rad_inch_aac])
    gmr_inch_combined = np.array([gmr_inch_acsr, gmr_inch_aaac, gmr_inch_aac])
    x_combined = np.array([[x_25_acsr, x_50_acsr, x_75_acsr],[x_25_aaac, x_50_aaac, x_75_aaac],[x_25_aac, x_50_aac, x_75_aac]])
    r_combined = np.array([[r_25_acsr, r_50_acsr, r_75_acsr],[r_25_aaac, r_50_aaac, r_75_aaac],[r_25_aac, r_50_aac, r_75_aac]])

    #now, let's convert everything to ohm/mile
    x_allTemp = x_combined * 5280 / 1000
    r_allTemp = r_combined * 5280 / 1000  

    # Radius and GMR in feet
    rad_feet_combined = rad_inch_combined / 12
    gmr_feet_combined = gmr_inch_combined / 12
    rad_pri_feet = rad_feet_combined[priTypeChoice][priSizeChoice]
    rad_neut_feet = rad_feet_combined[neutTypeChoice][neutSizeChoice]
    gmr_pri_feet = gmr_feet_combined[priTypeChoice][priSizeChoice]
    gmr_neut_feet = gmr_feet_combined[neutTypeChoice][neutSizeChoice]
    
    # calculations
    latLoadVec = [latLoadA, latLoadB, latLoadC]
    latLargestXFMR_Vec = [latLargestXFMR_A, latLargestXFMR_B, latLargestXFMR_C]
                 
    V_ph = V_ll / math.sqrt(3)

    r_phase = r_allTemp[priTypeChoice][condTempChoice][priSizeChoice]
    r_neutral = r_allTemp[neutTypeChoice][condTempChoice][neutSizeChoice]
    priResistiv = complex(r_phase, x_allTemp[priTypeChoice][condTempChoice][priSizeChoice])
    neutResistiv = complex(r_neutral, x_allTemp[neutTypeChoice][condTempChoice][neutSizeChoice])

    # substation data
    Z_base = (V_ll ** 2) / S_sc

    # calculate R and X using pythagorean theorem
    R_s = Z_base / math.sqrt((x_over_r ** 2) + 1)
    X_s = math.sqrt((Z_base ** 2) - (R_s ** 2))

    # we assume that the source is balanced
    Z_source_pos = complex(R_s, X_s)
    Z_source_zero = Z_source_pos

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

    I_012 = V_ph / Z_sum    # I0 = I1 = I2 for a SLG fault

    I_fLG_phasor = 3.0 * I_012
    I_fLG_magnitude = abs(I_fLG_phasor)
    I_f_feeder = I_fLG_magnitude

    # returnPhasor=True hands the complex fault current to latFuseCurrent so it
    # can recover the exact upstream impedance instead of assuming the source X/R
    if returnPhasor:
        return I_fLG_phasor
    return I_f_feeder

def latFuseCurrent(V_ll, I_f_previous, x_over_r, latLengthFt, latPriSizeChoice, latPriTypeChoice, latNeutSizeChoice, latNeutTypeChoice, soilResistivity, condTempChoice, D_an, returnPhasor=False):
    # note: latLengthFt is the distance from the previous fuse to this one
    # note: I_f_previous may be a magnitude or the complex phasor returned with returnPhasor=True
    
    #assumptions
    freq = 60 #Hz

    #tables
    condTempVec = [25, 50, 75] #deg C
                 
    condSize = ['4', '2', '1/0', '2/0', '4/0', '336.4', '477', '556.5']
    condType = ['ACSR', 'AAAC', 'AAC']

    # radius, gmr, resistance, and reactance for each onductor type and temperature combo
    rad_inch_acsr = np.array([0.1285, 0.1580, 0.1990, 0.2235, 0.2815, 0.3605, 0.4290, 0.4635])
    gmr_inch_acsr = np.array([0.0524, 0.0502, 0.0535, 0.0612, 0.0977, 0.2928, 0.4296, 0.4620])
    r_25_acsr = np.array([0.412, 0.259, 0.163, 0.130, 0.0822, 0.0523, 0.0369, 0.0318])
    r_50_acsr = np.array([0.479, 0.308, 0.197, 0.162, 0.1070, 0.0574, 0.0405, 0.0348])
    r_75_acsr = np.array([0.522, 0.336, 0.216, 0.176, 0.1160, 0.0625, 0.0441, 0.0379])
    x_25_acsr = np.array([0.115, 0.128, 0.116, 0.112, 0.0964, 0.0826, 0.0835, 0.0818])
    x_50_acsr = np.array([0.137, 0.123, 0.104, 0.113, 0.1050, 0.0826, 0.0835, 0.0818])
    x_75_acsr = np.array([0.131, 0.110, 0.114, 0.102, 0.1050, 0.0826, 0.0835, 0.0818])

    rad_inch_aaac = np.array([0.1250, 0.1580, 0.1990, 0.2235, 0.2815, 0.3600, 0.4290, 0.4635])
    gmr_inch_aaac = np.array([0.0908, 0.1147, 0.1445, 0.1623, 0.2044, 0.2729, 0.3252, 0.3513])
    r_25_aaac = np.array([0.4150, 0.2610, 0.1640, 0.1300, 0.0820, 0.0515, 0.0364, 0.0313])
    r_50_aaac = np.array([0.4510, 0.2840, 0.1780, 0.1410, 0.0891, 0.0560, 0.0396, 0.0340])
    r_75_aaac = np.array([0.4870, 0.3060, 0.1920, 0.1530, 0.0962, 0.0605, 0.0428, 0.0368])
    x_25_aaac = np.array([0.1120, 0.1066, 0.1013, 0.0987, 0.0934, 0.0867, 0.0827, 0.0809])
    x_50_aaac = x_25_aaac.copy()
    x_75_aaac = x_25_aaac.copy()

    rad_inch_aac = np.array([0.1160, 0.1460, 0.1840, 0.2070, 0.2610, 0.3330, 0.3975, 0.4290])
    gmr_inch_aac = np.array([0.0842, 0.1060, 0.1336, 0.1503, 0.1895, 0.2524, 0.3013, 0.3252])
    r_25_aac = np.array([0.4230, 0.2660, 0.1680, 0.1330, 0.0836, 0.0527, 0.0373, 0.0320])
    r_50_aac = np.array([0.4650, 0.2920, 0.1840, 0.1460, 0.0919, 0.0580, 0.0410, 0.0352])
    r_75_aac = np.array([0.5060, 0.3180, 0.2010, 0.1590, 0.1000, 0.0633, 0.0448, 0.0385])
    x_25_aac = np.array([0.1137, 0.1084, 0.1031, 0.1004, 0.0951, 0.0885, 0.0845, 0.0827])
    x_50_aac = x_25_aac.copy()
    x_75_aac = x_25_aac.copy()

    # combine the values into a matrix
    rad_inch_combined = np.array([rad_inch_acsr, rad_inch_aaac, rad_inch_aac])
    gmr_inch_combined = np.array([gmr_inch_acsr, gmr_inch_aaac, gmr_inch_aac])
    x_combined = np.array([[x_25_acsr, x_50_acsr, x_75_acsr],[x_25_aaac, x_50_aaac, x_75_aaac],[x_25_aac, x_50_aac, x_75_aac]])
    r_combined = np.array([[r_25_acsr, r_50_acsr, r_75_acsr],[r_25_aaac, r_50_aaac, r_75_aaac],[r_25_aac, r_50_aac, r_75_aac]])

    #now, let's convert everything to ohm/mile
    x_allTemp = x_combined * 5.28
    r_allTemp = r_combined * 5.28 

    # Radius and GMR in feet
    rad_feet_combined = rad_inch_combined / 12
    gmr_feet_combined = gmr_inch_combined / 12
    rad_pri_feet = rad_feet_combined[latPriTypeChoice][latPriSizeChoice]
    rad_neut_feet = rad_feet_combined[latNeutTypeChoice][latNeutSizeChoice]
    gmr_pri_feet = gmr_feet_combined[latPriTypeChoice][latPriSizeChoice]
    gmr_neut_feet = gmr_feet_combined[latNeutTypeChoice][latNeutSizeChoice]

    # Max Ampacity vector (Amperes)
    ampacity = np.array([140, 185, 240, 275, 365, 515, 640, 710])
    maxFuseForLat = np.array([140, 200, 200, 200, 200, 200, 200, 200])

    #calculations
    V_ph = V_ll / math.sqrt(3)

    if isinstance(I_f_previous, complex):
        # exact: the phasor carries the angle of everything upstream
        Z_sum_tap = (3.0 * V_ph) / I_f_previous
    else:
        # magnitude only: assume the upstream impedance has the source X/R
        abs_z_sum_tap = (3.0 * V_ph) / I_f_previous
        r_sum_tap = abs_z_sum_tap / math.sqrt((x_over_r ** 2) + 1.0)
        x_sum_tap = r_sum_tap * x_over_r
        Z_sum_tap = complex(r_sum_tap, x_sum_tap)

    r_phase_lat = r_allTemp[latPriTypeChoice][condTempChoice][latPriSizeChoice]
    r_neutral_lat = r_allTemp[latNeutTypeChoice][condTempChoice][latNeutSizeChoice]
    priResistiv_lat = complex(r_phase_lat, x_allTemp[latPriTypeChoice][condTempChoice][latPriSizeChoice])

    r_e = 0.001588 * freq
    D_e = 2160 * math.sqrt(soilResistivity / freq)
    
    z_aa = complex(r_phase_lat + r_e, 0.1213 * math.log(D_e / gmr_pri_feet))
    z_nn = complex(r_neutral_lat + r_e, 0.1213 * math.log(D_e / gmr_neut_feet))
    z_an = complex(r_e, 0.1213 * math.log(D_e / D_an))

    z_ae = z_aa - (z_an ** 2) / z_nn

    Z_line1_lat = priResistiv_lat * latLengthFt / 5280
    Z_line0_lat = z_ae * latLengthFt / 5280

    Z_sum_lat_total = Z_sum_tap + (2.0 * Z_line1_lat) + Z_line0_lat

    I_fLG_lat_phasor = 3.0 * V_ph / Z_sum_lat_total
    I_fLG_lat_magnitude = abs(I_fLG_lat_phasor)
    I_f_lateral = I_fLG_lat_magnitude

    if returnPhasor:
        return I_fLG_lat_phasor
    return I_f_lateral
   

def fuseSize(V_ll, I_LG_mag, downstreamPriSizeChoice, latLoadA, latLoadB, latLoadC, latLargestXFMR_A, latLargestXFMR_B, latLargestXFMR_C, largestChildNonTX):
    
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
    latLoadVec = [latLoadA, latLoadB, latLoadC]
    latLargestXFMR_Vec = [latLargestXFMR_A, latLargestXFMR_B, latLargestXFMR_C]
                 
    V_ph = V_ll / math.sqrt(3)

    # now, we calculate the largest transformer fuse
    V_ph_kV = V_ph / 1000
    transCurrent = max(latLargestXFMR_Vec) / V_ph_kV * 1.25

    #calculate the smallest fuse size that doesn't trip the largest transformer at 125% loading
    childFuseInd = -5
    for a in range(len(tSizes)):
        if transCurrent < tSizes[a]:
            childFuse = tSizes[a]
            childFuseInd = a
            break
    if childFuseInd == -5:
        childFuse = tSizes[-1]
        childFuseInd = len(tSizes) - 1
        warnings.warn("Largest downstream transformer needs more than a 200T link. Defaulting to maximum 200T.")

    #if the parent has a larger non-tx child fuse, then we use that as the largest child fuse
    if largestChildNonTX > childFuse:
        for a in range(len(tSizes)):
            if largestChildNonTX <= tSizes[a]:    # smallest T link that is at least the child fuse
                childFuse = tSizes[a]
                childFuseInd = a
                break
    if childFuse >= 140:
        parentSize = 200
        parentSizeInd = len(parent) - 1
    else:
        # now, with the child fuse and the fault current, we can calculate the fuse size
        parentSizeInd = -5
        for a in range(len(parent)):
            if faultTable[childFuseInd][a] > I_LG_mag:
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

    if ampacity[downstreamPriSizeChoice] < parentSize:
        warnings.warn("Required Fuse size is too large for selected downstream primary. Defaulting to maximum fuse for chosen wire size")
        parentSize = maxFuseForLat[downstreamPriSizeChoice]
    fuseSize = parentSize
    return fuseSize

def xfmrFuseSize(V_ll, latLargestXFMR_A, latLargestXFMR_B, latLargestXFMR_C):
    # transformer cutout: the same 125% rule fuseSize uses for the largest transformer fuse below it

    tSizes = [1, 2, 3, 6, 8, 10, 12, 15, 20, 25, 30, 40, 50, 65, 80, 100, 140, 200]

    # calculations
    latLargestXFMR_Vec = [latLargestXFMR_A, latLargestXFMR_B, latLargestXFMR_C]

    V_ph = V_ll / math.sqrt(3)

    # now, we calculate the largest transformer fuse
    V_ph_kV = V_ph / 1000
    transCurrent = max(latLargestXFMR_Vec) / V_ph_kV * 1.25

    #calculate the smallest fuse size that doesn't trip the largest transformer at 125% loading
    childFuseInd = -5
    for a in range(len(tSizes)):
        if transCurrent < tSizes[a]:
            childFuse = tSizes[a]
            childFuseInd = a
            break
    if childFuseInd == -5:
        childFuse = tSizes[-1]
        warnings.warn("Transformer needs more than a 200T link. Defaulting to maximum 200T.")

    return childFuse
