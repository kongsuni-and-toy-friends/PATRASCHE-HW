import socketio
import json
import requests
import uuid
from Google_STT import *
from Naver_TTS import *

serial_number = "abcd1234"
host = "http://125.6.39.158:5000"

sio = socketio.Client()

class TwoWayClient(object):
    def __init__(self):
        self.myname = "도담"
        self.nickname = "도담"
        self.mygender = "남자"
        self.soundData = ""
        self.limit_time = 30

        self.ListeningFlag = True
        self.CreateNameFlag = False
        self.MynameFlag = False
        self.MygenderFlag = False
        self.ClosedFlag = False
        self.ConversationFlag = False
        self.LimitTimeFlag = False
        self.PlayFlag = False

        self.high_count = False
        self.low_count = True

    def run(self):
        main(self, sio)

main_client = TwoWayClient()

@sio.on('connect', namespace='/realchat')
def connect():
    print("connected")
    sio.emit("join", {
        "serial_number": f"{serial_number}",
        "type": "CHILD"
    }, namespace='/realchat')  # 일로 보내기

@sio.on('disconnect', namespace='/realchat')
def disconnect():
    print('disconnected')

@sio.on("RECEIVE_MESSAGE", namespace='/realchat')
def RECEIVE_MESSAGE(data):
    print(list(data.values())[0])
    naver_tts(list(data.values())[0], main_client)


if __name__ == "__main__":
    print('start')
    main_client.run()
