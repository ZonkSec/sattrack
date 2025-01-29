import os
import threading
from io import StringIO,BytesIO
from RpiMotorLib import RpiMotorLib
from flask import Flask,request, render_template, redirect,Response
import concurrent.futures
import signal
import RPi.GPIO as GPIO
import sys
from skyfield.api import load,wgs84
from skyfield.iokit import parse_tle_file
from datetime import timedelta,timezone,datetime
from time import sleep
import requests
import csv

if not os.path.exists("key.pem") or not os.path.exists("cert.pem"):
   print("no certs found. make sure openssl is installed. generating...")
   os.system("openssl req -x509 -newkey rsa:2048 -nodes -out cert.pem -keyout key.pem -days 3650 -subj '/C=/ST=/L=/O=/CN='")

global lat
global long
global location_tz_offset
lat = None
long = None
location_tz_offset = 0

global tracking_thread
global stop_tracking
global tracking_sat_name
global tracking_sat_pos
global tracking_sat_events
global tracking_sat_cat
tracking_thread = None
stop_tracking = False
tracking_sat_pos = ""
tracking_sat_name = ""
tracking_sat_events = ""
tracking_sat_cat = ""

app = Flask(__name__)

@app.route("/config") 
def config(): 
  global lat
  global long
  global tracking_sat_name
  global current_az_pos
  global current_el_pos
  global location_tz_offset
  global tracking_sat_cat

  now = datetime.utcnow().strftime('%m/%d/%Y %H:%M:%S')

  if GPIO.input(4) == 1:
    steppers_disabled = True
  else:
    steppers_disabled = False
  
  if lat == None or long == None:
    gpsmissing = True
  else:
    gpsmissing = False
  return render_template("config.html",tracking_sat_cat=tracking_sat_cat,location_tz_offset=location_tz_offset,now=now,current_az_pos=current_az_pos,current_el_pos=current_el_pos,steppers_disabled=steppers_disabled,tracking_sat_name=tracking_sat_name,gpsmissing=gpsmissing,lat=lat,long=long)

@app.route("/set_tz") 
def set_tz_offset(): 
   global location_tz_offset
   location_tz_offset = int(request.args.get('offset'))
   return redirect(request.referrer)

@app.route("/view") 
def view():
  file = request.args.get('file')
  if file == "fmsattxt":
    try:
      with open('data/fm/satellites.txt', 'r') as file:
        file_content = file.read()
    except:
       file_content = "satellites.txt not found"
  elif file == "ssbsattxt":
    try:
      with open('data/ssb/satellites.txt', 'r') as file:
        file_content = file.read()
    except:
       file_content = "satellites.txt not found"
  else:
     if os.path.exists("data/ssb/filtered_TLE.txt") and os.path.exists("data/fm/filtered_TLE.txt"):
        fm_satellites = open('data/fm/filtered_TLE.txt', 'r').read()
        ssb_satellites = open('data/ssb/filtered_TLE.txt', 'r').read()
        file_content = fm_satellites + ssb_satellites
     else:
        file_content = "tle data missing"
  return Response(file_content, mimetype='text/plain')



@app.route('/motorEnable')
def enable():
   x = request.args.get('enabled')
   if x == "yes":
      GPIO.output(4, GPIO.LOW)
      return redirect(request.referrer)
   else:
      GPIO.output(4, GPIO.HIGH)
      return redirect(request.referrer)

@app.route('/shutdown')
def shutdown():
   os.system("sudo shutdown -h now")  
   return "Shutting down..."
   
@app.route('/homeAZEL')
def homeAZEL():
    if GPIO.input(4) == 1:
       return("steppers are disabled. not homing")
    if tracking_thread != None:
       return("actively tracking a sat. not homing")
    zero_EL()
    global current_az_pos
    current_az_pos = 0
    return redirect(request.referrer)

global moving 
moving = False
@app.route('/moveTo')
def moveTo():
    global current_az_pos
    global current_el_pos
    global tracking_thread
    global moving 

    if tracking_thread == None and moving == False:
      moving = True
      desired_az_pos = int(request.args.get('az',default=current_az_pos))
      desired_el_pos = int(request.args.get('el',default=current_el_pos))
      az_steps, az_direction = az_deg_to_steps_dir(desired_az_pos)
      el_steps,el_direction = el_deg_to_steps_dir(desired_el_pos)
      thread_move_steps(az_direction,az_steps,el_direction,el_steps)
      if az_steps > 0:
        current_az_pos = desired_az_pos
      if el_steps > 0:
          current_el_pos = desired_el_pos
      moving = False
      return redirect(request.referrer)
    else:
       return "cant manual move. active tracking is ongoing. or a manual move is active"

@app.route('/updateTLE')
def updateTLE():
    msg =update_sat_data()
    return msg

@app.route("/") 
@app.route('/passes',methods=['GET', 'POST'])
def listUpcomingPasses():
  global lat
  global long
  global tracking_sat_name
  global location_tz_offset
  global tracking_sat_cat

  if GPIO.input(4) == 1:
    steppers_disabled = True
  else:
     steppers_disabled = False

  if lat == None or long == None:
      gpsmissing = True
  else:
     gpsmissing = False

  if request.method == 'GET':
    return render_template("passes.html",method=request.method,tracking_sat_cat=tracking_sat_cat,steppers_disabled=steppers_disabled,tracking_sat_name=tracking_sat_name,gpsmissing=gpsmissing,lat=lat,long=long)
  if request.method == 'POST':
    if gpsmissing:
      return "lat or long not set"
  
    time = request.form.get('time')
    display_time = request.form.get('display_time')
    max_el = int(request.form.get('el',default=30))
    mode = request.form.get('mode')

    if time == None or max_el == None:
       return "pass input not set"

    ts = load.timescale()
    if mode == "fm":
      if os.path.exists("data/fm/filtered_TLE.txt"):
        satellites= load.tle_file('data/fm/filtered_TLE.txt')
      else:
        return "filtered_TLE not found. create it using 'Make/Update TLE via CelesTrak' on Config page"
    elif mode == "ssb":
      if os.path.exists("data/ssb/filtered_TLE.txt"):
        satellites= load.tle_file('data/ssb/filtered_TLE.txt')
      else:
        return "filtered_TLE not found. create it using 'Make/Update TLE via CelesTrak' on Config page"
    elif mode == "both":
       if os.path.exists("data/ssb/filtered_TLE.txt") and os.path.exists("data/fm/filtered_TLE.txt"):
        fm_satellites = open('data/fm/filtered_TLE.txt', 'r').read()
        ssb_satellites = open('data/ssb/filtered_TLE.txt', 'r').read()
        both = fm_satellites + ssb_satellites
        f = BytesIO(str.encode(both))
        satellites = list(parse_tle_file(f, ts))
       else:
        return "filtered_TLE not found. create it using 'Make/Update TLE via CelesTrak' on Config page"
    else:
      return "error on mode selection"

    location = wgs84.latlon(lat, long)
    if display_time == "local":
      location_tz = timezone(timedelta(hours=location_tz_offset))
    else:
       location_tz = timezone(timedelta(hours=0))

    t0 = ts.now()
    t1 = ts.utc(t0.utc_datetime() + timedelta(hours=int(time)))

    passes = {}
    passes_satcat = {}

    for satellite in satellites:
        t, events = satellite.find_events(location, t0, t1, altitude_degrees=max_el)
        event_names = 'Rise above '+str(max_el)+'°', 'Culminate', 'Set below '+str(max_el)+'°'
        my_events = []
        if len(events) != 0:
            for ti, event in zip(t, events):
                if event == 1:
                    difference = satellite - location
                    topocentric = difference.at(ti)
                    alt, az, distance = topocentric.altaz()
                    name = event_names[event] + ' ' + str(round(alt.degrees)) +'°'
                    timestamp = ti.astimezone(location_tz).strftime('%m/%d/%Y %H:%M:%S')
                else:
                    name = event_names[event]
                    timestamp = ti.astimezone(location_tz).strftime('%m/%d/%Y %H:%M:%S')
                my_events.append(f'{timestamp} {name}')
            passes[satellite.name]=my_events
            passes_satcat[satellite.name]=satellite.model.satnum
    passes_sorted = {}
    for x in (sorted(passes,key=passes.get)):
       passes_sorted[x]=passes[x]
       
  return render_template("passes.html",tracking_sat_cat=tracking_sat_cat,passes_satcat=passes_satcat,steppers_disabled=steppers_disabled,method=request.method,tracking_sat_name=tracking_sat_name,passes=passes_sorted,time=time,max_el=max_el,lat=lat,long=long,gpsmissing=gpsmissing)



@app.route('/getGPS')
def getGPS():
   global lat
   global long
   global location_tz_offset
   lat_param = request.args.get('lat')
   long_param = request.args.get('long')
   if not lat_param or not long_param:
    return """
  <script>navigator.geolocation.getCurrentPosition(function(location) {
    fetch("/getGPS?lat="+location.coords.latitude+"&long="+location.coords.longitude+"&next=" + document.referrer+"&utcoffset="+new Date().getTimezoneOffset(),{method: "GET"})
    .then(response => {
        if (response.redirected) {window.location.href = response.url}
        })});
  </script>
  """
   else:
        lat = float(lat_param)
        long = float(long_param)
        next = request.args.get('next')
        location_tz_offset = (int(request.args.get('utcoffset'))/60) * -1
        return redirect(next)

@app.route('/startTrack')
def track():
   global tracking_thread
   global tracking_sat_name
   global lat
   global long
   global tracking_sat_events
   sat = request.args.get('sat')
   if request.args.get('events'):
      tracking_sat_events = request.args.get('events').strip('[]').replace("\'", '').split(',')
   if lat == None or long == None:
     return "cant track. lat long not set"
   if tracking_thread is None:
      tracking_thread = threading.Thread(target = tracker, kwargs={'requested_sat':sat})
      tracking_thread.start()
      tracking_sat_name = sat
      return redirect("track")
   else:
        return("tracking already running. must kill first")

@app.route('/killTrack')
def stop():
    global stop_tracking
    global tracking_thread
    global tracking_sat_name
    global tracking_sat_events
    global tracking_sat_cat
    if tracking_thread is None:
        return redirect(request.referrer)
    else:
        stop_tracking = True
        tracking_thread.join()
        tracking_thread = None
        stop_tracking = False
        tracking_sat_name = ""
        tracking_sat_events = ""
        tracking_sat_cat = ""
        return redirect(request.referrer)

@app.route('/watchTracking')
def watch_track():
    global tracking_thread
    global tracking_sat_pos

    if tracking_thread is None:
        return "nothing is being track"
    else:
        def track_now():
            global tracking_sat_pos
            data = ""
            while True:
                data = tracking_sat_pos
                sleep(.1)
                yield data
    return track_now()

@app.route('/track')
def viewtrack():
    global tracking_thread
    global tracking_sat_pos
    global tracking_thread
    global tracking_sat_name
    global lat
    global long
    global tracking_sat_events
    global tracking_sat_cat

    if GPIO.input(4) == 1:
      steppers_disabled = True
    else:
      steppers_disabled = False

    if lat == None or long == None:
      gpsmissing = True
    else:
      gpsmissing = False

    sat_name_list = []
    if tracking_sat_name == "":
      with open('data/fm/satellites.txt', 'r') as csvfile:
        csvreader = csv.reader(csvfile)
        next(csvreader) #skip header line
        for row in csvreader:
          sat_name_list.append(row[1].strip())
      with open('data/ssb/satellites.txt', 'r') as csvfile:
        csvreader = csv.reader(csvfile)
        next(csvreader) #skip header line
        for row in csvreader:
          sat_name_list.append(row[1].strip())



    sat_name_list = sorted(sat_name_list)

    return render_template("tracking.html",tracking_sat_cat=tracking_sat_cat,tracking_sat_events=tracking_sat_events,steppers_disabled=steppers_disabled,tracking_sat_name=tracking_sat_name,sat_name_list=sat_name_list,tracking_thread=tracking_thread,lat=lat,long=long,gpsmissing=gpsmissing)

@app.after_request
def add_static_cache(response):
   if response.content_type in ["text/javascript; charset=utf-8",
                                "image/svg+xml; charset=utf-8",
                                "text/css; charset=utf-8",
                                "application/octet-stream"]:
      response.headers['Cache-Control'] = 'max-age=86400, public'  # Cache for 24 hours
   return response

GPIO.setwarnings(False)
GPIO.setmode(GPIO.BCM)
GPIO.setup(4, GPIO.OUT)#enable pin 
GPIO.output(4, GPIO.HIGH)#enable pin
GPIO.setup(13, GPIO.IN, pull_up_down=GPIO.PUD_DOWN) #endstop pin
GPIO.setup(18, GPIO.OUT) #buzzer pin

az_direction_pin = 20      
az_step_pin = 21
az_mode_pins = 22, 23, 24
az_a4988_nema = RpiMotorLib.A4988Nema(az_direction_pin, az_step_pin, az_mode_pins, "A4988")

el_direction_pin = 16    
el_step_pin = 17
el_mode_pins = 25, 26, 27
el_a4988_nema = RpiMotorLib.A4988Nema(el_direction_pin, el_step_pin, el_mode_pins, "A4988")

#full steps per rot = 200
#1/16 stepping steps per rot = 3200
#az gears 10:43 == 1:4.3
#az quater stepping full rotate steps = 13760
#az degs to steps = 13760/360 = 38.2222222222
steps_per_azDeg = 13760/360

#full steps per rot = 200
#half stepping steps per rot = 800
#el gears 1:30
#el quater stepping full rotate steps = 24000
#el degs to steps = 24000 / 360 = 5.5555
steps_per_elDeg = 24000 / 360

global current_az_pos
global current_el_pos
current_az_pos = 0
current_el_pos = 0


def buzz(freq,length):
  p = GPIO.PWM(18, freq)
  p.start(1)
  sleep(length)
  p.stop()

buzz(293*2,0.2)
buzz(329*2,0.2)
buzz(261*2,0.2)
buzz(130*2,0.2)
buzz(196*2,0.2)

def thread_move_steps(az_direction,az_steps,el_direction,el_steps):
  with concurrent.futures.ThreadPoolExecutor() as executor:
          az_steptype = "1/16"
          az_stepdelay = 0.0008
          az_initialdelay = 0.05
          el_steptype = "1/4"
          el_stepdelay = 0.0005
          el_initialdelay = 0.05
          f1 = executor.submit(az_a4988_nema.motor_go, az_direction, az_steptype , az_steps, az_stepdelay, False, az_initialdelay)
          f2 = executor.submit(el_a4988_nema.motor_go, el_direction, el_steptype , el_steps, el_stepdelay, False, el_initialdelay)
          

def az_deg_to_steps_dir(desired_az_pos):
  global current_az_pos
  print(f'current_az_pos: {current_az_pos}')
  if desired_az_pos > current_az_pos:
    deg_to_move = desired_az_pos - current_az_pos
    if deg_to_move > 180:
      #the other direction is shorter
      deg_to_move = 360 - (desired_az_pos - current_az_pos) 
      az_steps = int(deg_to_move * steps_per_azDeg)
      az_direction = True
    else: 
      az_steps = int(deg_to_move * steps_per_azDeg)
      az_direction = False
    
  if desired_az_pos < current_az_pos:
    deg_to_move = current_az_pos - desired_az_pos
    if deg_to_move > 180:
      #the other direction is shorter
      deg_to_move = 360 - (current_az_pos - desired_az_pos)
      az_steps = int(deg_to_move * steps_per_azDeg)
      az_direction = False
    else:
      az_steps = int(deg_to_move * steps_per_azDeg)
      az_direction = True
  
  if desired_az_pos == current_az_pos:
    #already at the AZ needed
    az_steps=0
    az_direction=True

  return az_steps, az_direction

def el_deg_to_steps_dir(desired_el_pos):
  global current_el_pos
  print(f'current_el_pos: {current_el_pos}')
  if desired_el_pos >= 0:
    if desired_el_pos > current_el_pos:
      deg_to_move = desired_el_pos - current_el_pos
      el_direction = True
      el_steps = int(deg_to_move * steps_per_elDeg)
    if desired_el_pos < current_el_pos:
      deg_to_move = current_el_pos - desired_el_pos
      el_steps = int(deg_to_move * steps_per_elDeg)
      el_direction = False
    if desired_el_pos == current_el_pos:
      #already at the EL needed
      el_steps=0
      el_direction=False
  else:
     el_steps = 0
     el_direction = True
    
  return el_steps,el_direction
  
def update_sat_data():
  url = 'https://celestrak.org/NORAD/elements/gp.php?GROUP=active&FORMAT=tle'
  r = requests.get(url, allow_redirects=True)
  open('data/celestrakTLEdata.txt', 'wb').write(r.content)
  missing_sats = []
  for mode in ["fm","ssb"]:
    satcat_list = []
    name_satcat_lookup = {}
    with open(f'data/{mode}/satellites.txt', 'r') as csvfile:
        csvreader = csv.reader(csvfile)
        next(csvreader) #skip header line
        for row in csvreader:
            name_satcat_lookup[row[0].strip()] = row[1].strip()
            satcat_list.append(row[0].strip())

    

    filtered_file = open(f'data/{mode}/filtered_TLE.txt', 'w')

    file = open('data/celestrakTLEdata.txt', 'r')
    lines = file.readlines()
    x = 0
    satcat_list = sorted(set(satcat_list)) # remove dups if any
    for x in range(len(lines)):
        if x%3==0:
            name = lines[x].strip()
            tle1 = lines[x+1].strip()
            tle2 = lines[x+2].strip()
            satcat = tle1[2:8]
            if satcat in satcat_list:
                filtered_file.write(name_satcat_lookup[satcat] + " ("+mode.upper()+")\n")
                filtered_file.write(tle1 + "\n")
                filtered_file.write(tle2 + "\n")
                satcat_list.remove(satcat)
                if len(satcat_list) == 0:
                  #got all the sats we need, stop processing
                  break
    if len(satcat_list) != 0:
       missing_sats.append(satcat_list)

  if len(missing_sats) != 0:
     #couldnt find tle for a sat
     return ("TLEs updated. couldnt find the following TLEs from satellites.txt in celestrak data: "+str(missing_sats))
  else:
     return "TLEs updated"

def handler(signum,frame):
  print("exiting... stopping motors and cleaning up GPIO")        
  az_a4988_nema.motor_stop()
  el_a4988_nema.motor_stop()
  GPIO.output(4, GPIO.HIGH)
  sys.exit()                



def zero_EL():
  az_direction = False
  az_steps = 0
  el_direction = False
  el_steps = 25
   
  while GPIO.input(13) == 0:
    buzz(1000,0.1)
    thread_move_steps(az_direction,az_steps,el_direction,el_steps)
  
  global current_el_pos
  current_el_pos = 0
   
def tracker(requested_sat):
  global current_az_pos
  global current_el_pos
  global lat
  global long
  global location_tz_offset
  global stop_tracking
  global tracking_sat_pos
  global tracking_sat_cat

  if lat == None or long == None:
     return "cant track. lat long not set"

  location = wgs84.latlon(lat, long)
  location_tz = timezone(timedelta(hours=location_tz_offset))

  ts = load.timescale()

  if os.path.exists("data/ssb/filtered_TLE.txt") and os.path.exists("data/fm/filtered_TLE.txt"):
    fm_satellites = open('data/fm/filtered_TLE.txt', 'r').read()
    ssb_satellites = open('data/ssb/filtered_TLE.txt', 'r').read()
    both = fm_satellites + ssb_satellites
    f = BytesIO(str.encode(both))
    satellites = list(parse_tle_file(f, ts))
  else:
     return "filtered_TLE not found. create it using 'Make/Update TLE via CelesTrak' on Config page"



  for satellite in satellites:
      if requested_sat in satellite.name:
          sat_to_track = satellite
  
  tracking_sat_cat = sat_to_track.model.satnum
  sat_status = "unknown"
  last_sat_status = "unknown"
  while True and not stop_tracking:
      print("sat_status:" + sat_status)
      if float(current_el_pos) > 0:
         sat_status = "up"
      else:
         sat_status = "down"
      
      if sat_status == "up" and last_sat_status not in ["up"]:
        buzz(1000,0.1)
        buzz(500,0.1)
        buzz(1000,0.1)
         
      difference = sat_to_track - location
      topocentric = difference.at(ts.utc(ts.now().utc_datetime() + timedelta(seconds=2))) #lead the sat a bit
      alt, az, distance = topocentric.altaz()
      print(f'AZ:{az}, EL:{alt}')
      tracking_sat_pos = f'AZ: {az}, EL: {alt}<br>'.replace("deg","°")

      desired_az_pos = az.degrees
      az_steps, az_direction = az_deg_to_steps_dir(desired_az_pos)
      print(f'az_steps: {az_steps}')
      
      desired_el_pos = alt.degrees
      if desired_el_pos < 0 and current_el_pos > 0:
         desired_el_pos = 0
      el_steps,el_direction = el_deg_to_steps_dir(desired_el_pos)
      print(f'el_steps: {el_steps}')

      thread_move_steps(az_direction,az_steps,el_direction,el_steps)
      if az_steps > 0:
        current_az_pos = desired_az_pos
      if el_steps > 0:
        current_el_pos = desired_el_pos
      
      last_sat_status = sat_status
      sleep(.0005)

def manual_move():
   global current_az_pos
   global current_el_pos
   while True:
    desired_az_pos = int(input('Move to Absolute AZ°: '))
    desired_el_pos = int(input('Move to Absolute EL°: '))
    az_steps, az_direction = az_deg_to_steps_dir(desired_az_pos)
    el_steps,el_direction = el_deg_to_steps_dir(desired_el_pos)
    thread_move_steps(az_direction,az_steps,el_direction,el_steps)
    if az_steps > 0:
      current_az_pos = desired_az_pos
    if el_steps > 0:
       current_el_pos = desired_el_pos
   

signal.signal(signal.SIGINT, handler)
if __name__ == '__main__':
    app.run(host='0.0.0.0',port=8443,ssl_context=("cert.pem", "key.pem"))