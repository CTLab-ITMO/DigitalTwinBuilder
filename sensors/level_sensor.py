import time
import random
import matplotlib.pyplot as plt
import datetime
import numpy as np
from drawnow import drawnow
import math

try:
    import OPi.GPIO as GPIO
except ImportError:
    print("OPi.GPIO не установлен.")
    class FakeGPIO:
        def setmode(self, mode):
            pass
        def setup(self, pin, mode):
            pass
        def input(self, pin):
            return 0
        def cleanup(self):
            pass
    GPIO = FakeGPIO()


class LevelSimulator:
    def __init__(self, base_level=0.5, level_change_rate=0.02, noise_level=0.01):
        self.base_level = base_level  
        self.level_change_rate = level_change_rate 
        self.noise_level = noise_level 
        self.start_time = time.time()

    def get_level(self):
        time_now = time.time() - self.start_time
        level = self.base_level + self.level_change_rate * time_now
        level +=  0.02 * math.sin(2 * math.pi * 0.2 * time_now)
        level += random.gauss(0, self.noise_level)
        return level


class OrangePiLevelSensor:
    def __init__(self, data_pin=7):
        self.data_pin = data_pin
        GPIO.setmode(GPIO.BOARD)
        GPIO.setup(self.data_pin, GPIO.IN)
        self.start_time = time.time()

    def get_level(self):
         try:
            time_now = time.time() - self.start_time
            # Вставьте реальное чтение с АЦП (или с датчика).
            # Пример: voltage = read_adc(self.data_pin), (функция read_adc должна быть реализована)
            # Далее преобразование напряжения в уровень.
            level =  0.4 + 0.1 * time_now + random.gauss(0, 0.01)
            return level # Заглушка.
         except Exception as e:
             print(f"Error reading level data: {e}")
             return None

    def cleanup(self):
        GPIO.cleanup()

def cur_graf():
    plt.title("Level Sensor")
    plt.ylim(0, 2) 
    plt.plot(nw, lw1, "g.-")
    plt.ylabel(r'$Level$')
    plt.xlabel(r'$номер \ измерения$')
    plt.grid(True)


def all_graf():
    plt.close()
    plt.figure()
    plt.title("Level Sensor\n" +
              str(count_v) + "-й эксперимент " +
              "(" + now.strftime("%d-%m-%Y %H:%M") + ")")
    plt.plot(n, l1, "g-")
    plt.ylabel(r'$Level$')
    plt.xlabel(r'$номер \ измерения$' +
               '; (период опроса датчика: {:.6f}, c)'.format(Ts))
    plt.grid(True)
    plt.show()

str_m = input("введите количество измерений: ")
m = eval(str_m)
mw = 16

mode = input("Выберите режим работы ('real' для реального датчика, 'sim' для симуляции): ").lower()

if mode == 'real':
    level_sensor = OrangePiLevelSensor()
else:
    level_sensor = LevelSimulator()

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
print("L - уровень;")
print("\n измеряемые значения величины уровня\n")
print('{0}{1}\n'.format('n'.rjust(4), 'L'.rjust(10)))

i = 0
while i < m:
    n.append(i)
    nw.append(n[i])
    if i >= mw:
        nw.pop(0)

    if mode == 'real':
         simulated_level = level_sensor.get_level()
    else:
         simulated_level = level_sensor.get_level()


    if simulated_level is not None:
        t1.append(time.time())
        l1.append(simulated_level)
        lw1.append(l1[i])
        if i >= mw:
            lw1.pop(0)
        print('{0:4d} {1:10.4f}'.format(n[i], simulated_level))
        drawnow(cur_graf)
    else:
        print('{0:4d} {1}'.format(n[i], "No data received"))
        time.sleep(0.1)
    i += 1
if mode == 'real':
    level_sensor.cleanup()

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