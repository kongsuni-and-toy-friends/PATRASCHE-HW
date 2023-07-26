import urllib.request
import sys
import os
import re
# import pygame

from KD import *

YELLOW = "\033[0;33m" # 노란색 코드
WHITE = "\033[0;37m" # 하얀색 코드

#Naver tts ID infomation
client_id = "205v4olgcj"
client_secret = "AIEPJj8PG8DjNoJBF7G9PUbumNDVvFdVKv73HOQO"

#MP3 재생
def playSound(mySound):
    os.system("mpg123 " + mySound)
    # pygame.mixer.music.init() # initializing the module
    # pygame.mixer.music.load(mySound) # loading the ogg file
    # pygame.mixer.music.play() # this will simply play the loaded file.

def naver_tts(clientText, my_TwoWayClient):
    my_TwoWayClient.ListeningFlag = False

    encText = urllib.parse.quote(str(clientText))
    if re.search("(남자)", my_TwoWayClient.mygender):
        my_TwoWayClient.soundData = "speaker=nhajun&volume=0&speed=0&pitch=0&format=mp3&text=" + encText;
    else:
        my_TwoWayClient.soundData = "speaker=ngaram&volume=0&speed=0&pitch=0&format=mp3&text=" + encText;

    url = "https://naveropenapi.apigw.ntruss.com/tts-premium/v1/tts"
    request = urllib.request.Request(url)
    request.add_header("X-NCP-APIGW-API-KEY-ID", client_id)
    request.add_header("X-NCP-APIGW-API-KEY", client_secret)
    response = urllib.request.urlopen(request, data=my_TwoWayClient.soundData.encode('utf-8'))
    rescode = response.getcode()

    if (rescode == 200):
        print("TTS mp3 저장")
        response_body = response.read()

        with open('naverTTS.mp3', 'wb') as f:
            f.write(response_body)
            sys.stdout.write(YELLOW)  # 노란색 옵션
            print(clientText)
            playSound("naverTTS.mp3")
            sys.stdout.write(WHITE)  # 하얀색 옵션
            print("음성 끝")

            my_TwoWayClient.ListeningFlag=True
    else:
        sys.stdout.write(YELLOW)  # 노란색 옵션
        print("Error Code:" + rescode)