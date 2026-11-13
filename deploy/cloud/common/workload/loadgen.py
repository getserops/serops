"""Steady traffic on the shop frontend: about RPS requests a second."""
import os, threading, time, urllib.request

URL = os.environ.get('TARGET', 'http://frontend:8080/')
RPS = float(os.environ.get('RPS', '15'))


def hit():
    try:
        urllib.request.urlopen(URL, timeout=5).read()
    except Exception:
        pass


while True:
    threading.Thread(target=hit, daemon=True).start()
    time.sleep(1 / RPS)
