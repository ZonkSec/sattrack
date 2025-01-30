from RpiMotorLib import RpiMotorLib
import RPi.GPIO as GPIO
import concurrent.futures
import sys
import signal

GPIO.setwarnings(False)
GPIO.setmode(GPIO.BCM)
GPIO.setup(4, GPIO.OUT)#enable pin 
GPIO.output(4, GPIO.LOW)#enable pin

az_direction_pin = 20      
az_step_pin = 21
az_mode_pins = 22, 23, 24
az_a4988_nema = RpiMotorLib.A4988Nema(az_direction_pin, az_step_pin, az_mode_pins, "A4988")

el_direction_pin = 16    
el_step_pin = 17
el_mode_pins = 25, 26, 27
el_a4988_nema = RpiMotorLib.A4988Nema(el_direction_pin, el_step_pin, el_mode_pins, "A4988")

steptype = "Full"
stepdelay = 0.0005
verbose = False
initialdelay = 0.05

def handler(signum,frame):
  print("exiting... stopping motors and cleaning up GPIO")        
  az_a4988_nema.motor_stop()
  el_a4988_nema.motor_stop()
  GPIO.output(4, GPIO.HIGH)
  sys.exit()         

signal.signal(signal.SIGINT, handler)

with concurrent.futures.ThreadPoolExecutor() as executor:
        f1 = executor.submit(az_a4988_nema.motor_go, False, steptype , 0, stepdelay, False, initialdelay)
        f2 = executor.submit(el_a4988_nema.motor_go, False, steptype , 0, stepdelay, False, initialdelay)

input("Press any key to end...")

az_a4988_nema.motor_stop()
el_a4988_nema.motor_stop()
GPIO.output(4, GPIO.HIGH)
GPIO.cleanup()
