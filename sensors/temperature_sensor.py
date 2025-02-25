import time
import random
import matplotlib.pyplot as plt
import datetime
import numpy as np
from drawnow import drawnow
import math


class TemperatureSimulator:
    def __init__(self, base_temp=25, target_temp=35, time_constant=50, random_range=0.3):
        self.base_temp = base_temp
        self.target_temp = target_temp
        self.time_constant = time_constant
        self.random_range = random_range
        self.measurement_count = 0

    def get_temperature(self):
        time = self.measurement_count
        temp_diff = self.target_temp - self.base_temp
        temp = self.base_temp + temp_diff * (1 - math.exp(-time / self.time_constant))  
        temp += random.uniform(-self.random_range, self.random_range)
        self.measurement_count += 1
        return temp

    def reset_count(self):
        self.measurement_count = 0


class SimulatedDS18B20Sensor:
    def __init__(self, base_temp=25, temp_range=5, noise_level=0.5):
        self.base_temp = base_temp
        self.temp_range = temp_range
        self.noise_level = noise_level

    def get_temperature(self):
        temp = self.base_temp + random.uniform(-self.temp_range, self.temp_range)
        temp += random.gauss(0, self.noise_level)  
        return temp


def cur_graf():
    plt.title("DS18B20")
    plt.ylim(20, 40)
    plt.plot(nw, lw1, "r.-")
    plt.ylabel(r'$температура, \degree С$')
    plt.xlabel(r'$номер \ измерения$')
    plt.grid(True)


def all_graf():
    plt.close()
    plt.figure()
    plt.title("DS18B20\n" +
              str(count_v) + "-й эксперимент " +
              "(" + now.strftime("%d-%m-%Y %H:%M") + ")")
    plt.plot(n, l1, "r-")
    plt.ylabel(r'$температура, \degree С$')
    plt.xlabel(r'$номер \ измерения$' +
               '; (период опроса датчика: {:.6f}, c)'.format(Ts))
    plt.grid(True)
    plt.show()


str_m = input("введите количество измерений: ")
m = eval(str_m)
mw = 16

mode = input("Выберите режим работы ('real' для реального датчика, 'sim' для симуляции): ").lower()

if mode == 'real':
    temp_sensor = SimulatedDS18B20Sensor()
else:
    temp_simulator = TemperatureSimulator()


l1 = [] 
t1 = []
lw1 = [] 
n = [] 
nw = [] 
filename = 'count.txt'
try:
    in_file = open(filename, "r")
    count = in_file.read().strip()
    if count:
        try:
            count_v = eval(count) + 1
        except:
            count_v = 1
    else:
        count_v = 1
    in_file.close()
except FileNotFoundError:
    count_v = 1

in_file = open(filename, "w")
count = str(count_v)
in_file.write(count)
in_file.close()
filename = str(count_v) + '_' + filename
out_file = open(filename, "w")

print("\n параметры:\n")
print("n - номер измерения;")
print("T - температура, град. С;")
print("\n измеряемые значения величины температуры\n")
print('{0}{1}\n'.format('n'.rjust(4), 'T'.rjust(10)))

i = 0
while i < m:
    n.append(i)
    nw.append(n[i])
    if i >= mw:
        nw.pop(0)

    if mode == 'real':
        simulated_temp = temp_sensor.get_temperature()
    else:
        simulated_temp = temp_simulator.get_temperature()


    if simulated_temp is not None:
        t1.append(time.time())
        l1.append(simulated_temp)
        lw1.append(l1[i])
        if i >= mw:
            lw1.pop(0)
        print('{0:4d} {1:10.2f}'.format(n[i], simulated_temp))
        drawnow(cur_graf)
    else:
        print('{0:4d} {1}'.format(n[i], "No data received"))
        time.sleep(0.1)
    i += 1

time_tm = t1[m - 1] - t1[0]
print("\n продолжительность времени измерений: {0:.3f}, c".format(time_tm))
Ts = time_tm / (m - 1)
print("\n период опроса датчика: {0:.6f}, c".format(Ts))

print("\n таблица находится в файле {}\n".format(filename))
for i in np.arange(0, len(n), 1):
    count = str(n[i]) + "\t" + str(l1[i]) + "\n"
    out_file.write(count)

out_file.close()
out_file.closed

now = datetime.datetime.now()

all_graf()
end = input("\n нажмите Ctrl-C, чтобы выйти ")