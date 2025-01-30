# Setup

First setup you raspberry pi as you would normally. Next move the "app" directory to whereever you want the app to run from. I put mine in `/home/pi/`

Next install the dependies using `pip install -r requirements.txt`, you may need to use `--break-system-packages` to allow it to install the libraries to the shared system packages.

While in the `/app` directory, run the application like so `python tracker.py`. If this is the first time you have run, it may take a bit as it needs to generate SSL/TLS certicates so that the website can operated via HTTPS.

You should get output like this when the server is up and running:
```
 * Serving Flask app 'tracker'
 * Debug mode: off
WARNING: This is a development server. Do not use it in a production deployment. Use a production WSGI server instead.
 * Running on all addresses (0.0.0.0)
 * Running on https://127.0.0.1:8443
 * Running on https://192.168.1.50:8443

```

You can access it via the IP address listed there. You may be able to access if via `[hostname].local:8443` depending on your network. I set my hostname to sattrack, so I can access it via `sattrack.local:8443`

If you wan the script to start automatically with the py, run `crontab -e`. And then add the following lines:
```
@reboot rm /home/pi/tracker.log
@reboot sleep 10 && cd /home/pi/app && python tracker.py >/home/pi/tracker.log 2>&1 &
```

The second line is what runs the app. It also sets it's output to be logged to `/home/pi/tracker.log`. The first line cleans up this log at boot. So at the log will only contain output from a single run. The sleep on the second line prevents the first line from removing the current log, which happens if line 1 and 2 run at the same time.
