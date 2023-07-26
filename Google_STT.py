"""Google Cloud Speech API sample application using the streaming API.

NOTE: This module requires the dependencies `pyaudio` and `termcolor`.
To install using pip:

    pip install pyaudio
    pip install termcolor

"""

import re
import sys
import time
import os
from threading import Thread
import logging
from google.cloud import speech
import pyaudio
from six.moves import queue

from KD import *
from Naver_TTS import *

# 환경변수 path 설정
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "/home/pi/stt123.json"

# 웹소켓 통신
host = "http://125.6.39.158:5000"

# Audio recording parameters
STREAMING_LIMIT = 240000 # 4 minutes
SAMPLE_RATE = 16000
CHUNK_SIZE = int(SAMPLE_RATE / 10) # 100ms, 1600

RED = "\033[0;31m" # 빨간색 코드
GREEN = "\033[0;32m" # 초록색 코드
YELLOW = "\033[0;33m" # 노란색 코드
WHITE = "\033[0;37m" # 하얀색 코드

soundCount_high = 0 # 소리 높낮이 조절 멘트 종류 다양화
soundCount_low = 0

# 현 시간 출력 함수
def get_current_time():
    return int(round(time.time() * 1000))

class ResumableMicrophoneStream:
	# 생성자 함수
    def __init__(self, rate, chunk_size):
        self._rate = rate # sample rate 초기화
        self.chunk_size = chunk_size # chunk size 초기화
        self._num_channels = 1 # num channel 1로 초기화
        self._buff = queue.Queue() # 마이크 입력 버퍼 생성
        self.closed = True # 종료 close = True
        self.start_time = get_current_time() # start_time은 현 시간 출력 함수값
        self.restart_counter = 0 # 재시작 카운트 초기화
        self.audio_input = [] # 오디오 입력 list로 선언
        self.last_audio_input = [] # 마지막 오디오 입력 list 선언
        self.result_end_time = 0 # 결과 끝 시간 0으로 초기화
        self.is_final_end_time = 0 # 최종 끝 시간 0으로 초기화
        self.final_request_end_time = 0 # 최종 요구 끝시간 0으로 초기화
        self.bridging_offset = 0 # 오디오 실시간 데이터 전송 브릿지 0 초기화
        self.last_transcript_was_final = False # 마지막 번역이 최종 = False
        self.new_stream = True # new stream = True
        self._audio_interface = pyaudio.PyAudio() # portaudio 시스템 설정 -> PyAudio 인스턴스화
        self._audio_stream = self._audio_interface.open(
            format=pyaudio.paInt16, # 비트 깊이 = 16bits
            channels=self._num_channels, # 채널 설정
            rate=self._rate, # 샘플 rate 설정
            input=True, # 입력 stream인지 아닌지 설정 -> True
            frames_per_buffer=self.chunk_size, # Chunk의 크기 설정
            stream_callback=self._fill_buffer, # 버퍼가 쌓이면 _fill_buffer 콜백 함수가 호출. 즉, 마이크 입력을 _fill_buffer 콜백 함수로 전달받고 음성 데이터 stream 열음.
        )

	# class 열면 발생
    def __enter__(self):
        self.closed = False # 종료 close = False
        return self

	# class 종료시 발생
    def __exit__(self, type, value, traceback):
        self._audio_stream.stop_stream() # 스트림 닫기
        self._audio_stream.close() # 스트림 종료
        self.closed = True # 종료 close = True
        # Signal the generator to terminate so that the client's
        # streaming_recognize method will not block the process termination.
        self._buff.put(None) # 버퍼(큐)에 데이터 입력 없음
        self._audio_interface.terminate() # portaudio 세션 종료

	# 마이크 버퍼가 쌓일 때(Chunk = 1600) 이 함수 호출
    def _fill_buffer(self, in_data, *args, **kwargs):
        self._buff.put(in_data) # 버퍼에 in_data 입력
        return None, pyaudio.paContinue # portaudio 콜백 return

    # 클래스 종료될 때까지 무한 루프 돌림
    def generator(self, my_TwoWayClient):
        """Stream Audio from microphone to API and to local buffer"""
        while not self.closed: # closed == False 일때 계속 반복 실행 {
            data = [] # data list 선언

            if self.new_stream and self.last_audio_input: # new stream과 마지막 오디오 입력이 True 일 경우 {

                chunk_time = STREAMING_LIMIT / len(self.last_audio_input) # chunk time = (스트리밍 4분 / 마지막 오디오 입력 배열 길이)

                if chunk_time != 0: # chunk time이 0이 아닐 경우 {

                    if self.bridging_offset < 0: # 데이터 전송 브릿지가 음수 일 경우 {
                        self.bridging_offset = 0 # 브릿지 값 = 0 }

                    if self.bridging_offset > self.final_request_end_time: # 브릿지 값이 최종 요구 끝시간 보다 클 경우 {
                        self.bridging_offset = self.final_request_end_time # 브릿지 값 = 최종 요구 끝시간 }

                    chunks_from_ms = round(
                        (self.final_request_end_time - self.bridging_offset)
                        / chunk_time
                    ) # ms chunk 값 = [(최종 요구 끝시간 - 브릿지 값) / chunk time]

                    self.bridging_offset = round(
                        (len(self.last_audio_input) - chunks_from_ms) * chunk_time
                    ) # 브릿지 값 = [(마지막 오디오 입력 길이 - ms chunk 값) * chunk time]

                    for i in range(chunks_from_ms, len(self.last_audio_input)): # ms chunk 값부터 마지막 오디오 입력 길이 까지 반복 {
                        data.append(self.last_audio_input[i]) # 마지막 오디오 입력들 data list에 추가 } }

                self.new_stream = False # new stream = False로 if 탈출 }

            # Use a blocking get() to ensure there's at least one chunk of
            # data, and stop iteration if the chunk is None, indicating the
            # end of the audio stream.

            chunk = self._buff.get() # chunk = 버퍼에서 제일 먼저 insert 된 데이터
            self.audio_input.append(chunk) # 오디오 입력에 chunk 데이터 추가

            if chunk is None: # chunk 값이 없거나, 정의되지 않거나, 알 수 없을 경우 {
                return # generator 함수 빠져나감 --> end of audio stream }
            data.append(chunk) # data list에 chunk 데이터 삽입

            # Now consume whatever other data's still buffered.

            while True: # 계속 반복 {
                try: # 실행할 코드
                    chunk = self._buff.get(block=False) # chunk = 버퍼 첫 인자

                    if chunk is None: # chunk에 값을 할당받지 못한 경우 {
                        return # generator 함수 탈출 }
                    data.append(chunk) # data list에 chunk 데이터 삽입
                    self.audio_input.append(chunk) # 오디오 입력에 chunk 데이터 추가

                except queue.Empty: # 큐가 비어있을 경우
                    break # while문 탈출 }

            if my_TwoWayClient.ListeningFlag: # ListeningFlag가 True인 경우 {
                yield b"".join(data) # byte 형식으로 yield에 data 문자열 형태로 인코딩 }
            else:
                data = []
                yield b"".join(data)

# 서버 응답 반복하고 print하는 함수
def listen_print_loop(responses, stream, my_TwoWayClient, sio): # responses는 generator로부터 받아온 문자열
    # stream은 ResumableMicrophoneStream 객체 / my_TwoWayClient은 WebSocket 객체
    """Iterates through server responses and prints them.

    The responses passed is a generator that will block until a response
    is provided by the server.

    Each response may contain multiple results, and each result may contain
    multiple alternatives; for details, see https://goo.gl/tjCPAU.  Here we
    print only the transcription for the top alternative of the top result.

    In this case, responses are provided for interim results as well. If the
    response is an interim one, print a line feed at the end of it, to allow
    the next result to overwrite it, until the response is a final one. For the
    final one, print a newline to preserve the finalized transcription.
    """
    global soundCount_high
    global soundCount_low
    
    for response in responses: # responses 만큼 반복 {
        if get_current_time() - stream.start_time > STREAMING_LIMIT: # 현 시간 - stream 시작 시간 > 4분일 경우 {
            stream.start_time = get_current_time() # stream 시작 시간 = 현재 시간
            my_TwoWayClient.LimitTimeFlag = True
            break # for문 탈출 }

        if not response.results: # response의 번역 list 값이 없다면 {
            continue # for문 처음으로 돌아가 }

        result = response.results[0] # result = response의 번역 list 처음 문자

        if not result.alternatives: # result의 인식 가설 대안이 존재 하지 않을 경우 {
            continue # for문 처음으로 돌아가 }

        transcript = result.alternatives[0].transcript # transcript = result의 인식 가설 대안 처음 문자

        result_seconds = 0 # result sec = 0
        result_micros = 0 # result us = 0

        if result.result_end_time.seconds: # result의 결과 끝시간의 sec가 0이 아닌 경우 {
            result_seconds = result.result_end_time.seconds # result sec = result의 결과 끝시간의 sec }

        if result.result_end_time.microseconds: # result의 결과 끝시간 us가 0이 아닌 경우 {
            result_micros = result.result_end_time.microseconds # result us = result의 결과 끝시간 us }

        stream.result_end_time = int((result_seconds * 1000) + (result_micros / 1000)) # stream의 결과 끝시간 = (result sec * 1000) + (result us / 1000)

        corrected_time = (
            stream.result_end_time
            - stream.bridging_offset
            + (STREAMING_LIMIT * stream.restart_counter)
        ) # 정정 시간 = stream의 결과 끝시간 - stream의 브릿지 값 + (4분 * stream의 재시작 카운터)

        # Display interim results, but with a carriage return at the end of the
        # line, so subsequent lines will overwrite them.

        # if GPIO.input(4) == GPIO.HIGH and not my_TwoWayClient.high_count :
        #     naver_tts("배터리 충전을 시작합니다!", my_TwoWayClient)
        #     my_TwoWayClient.high_count = True
        #     my_TwoWayClient.low_count = False
        #
        # if GPIO.input(4) == GPIO.LOW and not my_TwoWayClient.low_count :
        #     naver_tts("배터리 충전을 종료합니다!", my_TwoWayClient)
        #     my_TwoWayClient.high_count = False
        #     my_TwoWayClient.low_count = True

        if result.is_final:
            if re.search("(서방아|부담 아|보람아|고다마|부담아|또 담아|더담아|버담아|도라마|보담아|다담아|토다 마|소드 마|소담아|부담 안|보다나|돋아나|우다 마|오바마|보다 맘)", transcript):
                transcript = "도담아"
            sys.stdout.write(GREEN)  # 초록색 옵션
            sys.stdout.write("\033[K")  # clear line
            sys.stdout.write(str(corrected_time) + ": " + transcript + "\n")  # "정정시간 : 번역 문장" 출력

            stream.is_final_end_time = stream.result_end_time  # stream의 최종 끝시간 = stream의 결과 끝시간
            stream.last_transcript_was_final = True  # stream의 마지막 번역이 최종 = True

            if my_TwoWayClient.CreateNameFlag == True:
                correction = transcript[:-1]
                name = correction[1:]
                my_TwoWayClient.nickname = name
                naver_tts("너가 정해준 이름은 " + my_TwoWayClient.nickname + "이구나! 정말 고마워!", my_TwoWayClient)
                my_TwoWayClient.CreateNameFlag = False
                my_TwoWayClient.MynameFlag = False

            elif my_TwoWayClient.MygenderFlag == True:
                transcript = transcript[:-1]
                my_TwoWayClient.mygender = transcript
                naver_tts("내 목소리를 바꿔봤어! 마음에 들길 바래.", my_TwoWayClient)
                my_TwoWayClient.MygenderFlag = False
                my_TwoWayClient.MynameFlag = False

            elif my_TwoWayClient.ConversationFlag == True:
                if (re.search(str(my_TwoWayClient.myname), transcript) or re.search(str(my_TwoWayClient.nickname), transcript)) and re.search("(고마워|해결)", transcript):
                    naver_tts("에이, 아무것도 아니야! 히히", my_TwoWayClient)
                    my_TwoWayClient.ConversationFlag = False
                    my_TwoWayClient.MynameFlag = False

                elif (re.search(str(my_TwoWayClient.myname), transcript) or re.search(str(my_TwoWayClient.nickname), transcript)) and re.search("(잘 있어|내일 봐|다음에 봐|내일 보자|다음에 보자)", transcript):
                    naver_tts("알았어, 다음에 또 봐!", my_TwoWayClient)
                    my_TwoWayClient.ConversationFlag = False
                    my_TwoWayClient.MynameFlag = False

                elif (re.search(str(my_TwoWayClient.myname), transcript) or re.search(str(my_TwoWayClient.nickname), transcript)) and re.search("(잘 자|꿈 꿔)", transcript):
                    naver_tts("오늘 하루도 정말 고생했어. 잘 자!", my_TwoWayClient)
                    my_TwoWayClient.ConversationFlag = False
                    my_TwoWayClient.MynameFlag = False

                else:
                    sio.emit("SEND_MESSAGE", {"message": transcript, "type": "CHILD"}, namespace='/realchat')
                    #my_TwoWayClient.chat.emit('message', {"message": transcript})  # 서버에 웹소켓 전송 }

            elif my_TwoWayClient.PlayFlag == True:
                correction = transcript[:-1]
                word = correction[1:]
                end_to_end(my_TwoWayClient, word)

            elif my_TwoWayClient.CreateNameFlag == False and my_TwoWayClient.MygenderFlag == False and my_TwoWayClient.ConversationFlag == False and my_TwoWayClient.PlayFlag == False:

                if my_TwoWayClient.MynameFlag == True: # 활성화 모드

                    if re.search(str(my_TwoWayClient.myname), transcript) or re.search(str(my_TwoWayClient.nickname), transcript):
                        naver_tts("응? 왜 불러?", my_TwoWayClient)
                    #-----------------------------------------------------------------------------------------------------------------------------------
                    elif re.search("(이름)", transcript) and re.search("(바꾸|바꿔|바꿀)", transcript):
                        naver_tts("내 새로운 이름을 불러줘!", my_TwoWayClient)
                        my_TwoWayClient.CreateNameFlag = True

                    elif re.search("(너|당신|네)", transcript) and re.search("(이름)", transcript) and re.search("(뭐|모|무엇|누구)", transcript):
                        naver_tts("내 이름은 " + my_TwoWayClient.myname + " 이야! 잘 부탁해!", my_TwoWayClient)
                        my_TwoWayClient.MynameFlag = False

                    elif re.search("(심심|끝말잇기|게임)", transcript):
                        naver_tts("심심할 땐 끝말잇기지! 너 먼저 시작해줘!", my_TwoWayClient)
                        my_TwoWayClient.PlayFlag = True

                    elif re.search("(목소리|성별)", transcript) and re.search("(바꾸|바꿔|바꿀)", transcript):
                        naver_tts("목소리를 바꿔볼게! 여자가 좋을까, 남자가 좋을까?", my_TwoWayClient)
                        my_TwoWayClient.MygenderFlag = True

                    elif re.search("(소리|음성)", transcript) and re.search("(높|커|크|키)", transcript):
                        volumeMasterUP()
                        if soundCount_high == 0:
                            naver_tts("목소리를 크게 해볼게!", my_TwoWayClient)
                            soundCount_high = 1
                        elif soundCount_high == 1:
                            naver_tts("더 큰 목소리로 말해볼게!", my_TwoWayClient)
                            soundCount_high = 2
                        elif soundCount_high == 2:
                            naver_tts("지금도 작니? 목소리를 더 키워봤어!", my_TwoWayClient)
                            soundCount_high = 0
                        my_TwoWayClient.MynameFlag = False

                    elif re.search("(소리|음성)", transcript) and re.search("(낮|작|줄)", transcript):
                        volumeMasterDOWN()
                        if soundCount_low == 0:
                            naver_tts("목소리를 작게 해볼게!", my_TwoWayClient)
                            soundCount_low = 1
                        elif soundCount_low == 1:
                            naver_tts("더 작은 목소리로 말해볼게!", my_TwoWayClient)
                            soundCount_low = 2
                        elif soundCount_low == 2:
                            naver_tts("지금도 크니? 목소리를 낮춰봤어!", my_TwoWayClient)
                            soundCount_low = 0
                        my_TwoWayClient.MynameFlag = False

                    elif re.search("(노래)", transcript) and re.search("(불러|틀어|듣)", transcript):
                        naver_tts("내가 귀여운 당근송을 들려줄게!", my_TwoWayClient)
                        playSound("30sec_BGM.mp3")
                        my_TwoWayClient.MynameFlag = False

                    elif re.search("(날씨)", transcript) and re.search("(어때|알려|어떻|어떠)", transcript):
                        naver_tts("현재 " + str(find_address()) + "의 날씨는 " + str(find_current_weather()) + "이야. 기온은 "
                                  + str(find_current_temp()) + "도 이고, 미세먼지 농도는 " + str(find_current_dust()) + "이야. 오늘도 기분 좋은 하루 되렴~!", my_TwoWayClient)
                        my_TwoWayClient.MynameFlag = False

                    elif re.search("(배터리)", transcript) and re.search("(어때|알려|어떻|알려|남)", transcript):
                        naver_tts("현재 배터리 잔량은 " + str(readCapacity(bus)) + "%야!", my_TwoWayClient)
                        if readCapacity(bus) > 95 :
                            naver_tts("배터리가 가득 차있어!", my_TwoWayClient)
                            my_TwoWayClient.MynameFlag = False
                        elif readCapacity(bus) <= 95 and readCapacity(bus) > 50 :
                            naver_tts("배터리가 충분히 남아있어!", my_TwoWayClient)
                            my_TwoWayClient.MynameFlag = False
                        elif readCapacity(bus) <= 50 and readCapacity(bus) > 10 :
                            naver_tts("슬슬 배가 고파지는 것 같애!", my_TwoWayClient)
                            my_TwoWayClient.MynameFlag = False
                        elif readCapacity(bus) <= 10 and readCapacity(bus) > 0 :
                            naver_tts("나를 바구니 안에 넣어줘!", my_TwoWayClient)
                            my_TwoWayClient.MynameFlag = False

                    elif re.search("(완전 종료)", transcript):
                        sys.stdout.write(WHITE)  # 하얀색 옵션
                        naver_tts("완전 종료를 실시합니다.", my_TwoWayClient)
                        sys.stdout.write("종료 중...\n")  # 종료 중... 출력
                        my_TwoWayClient.ClosedFlag = True
                        stream.closed = True  # stream의 중지 closed = True
                        break  # for문 탈출 } }


                    elif re.search("(잘 잤)", transcript):
                        naver_tts("일어났구나! 나도 푹 잔 것 같아!", my_TwoWayClient)
                        my_TwoWayClient.MynameFlag = False

                    elif re.search("(좋은 아침)", transcript):
                        naver_tts("좋은 아침이야! 오늘 하루도 힘차게 시작해보자!", my_TwoWayClient)
                        my_TwoWayClient.MynameFlag = False

                    #-------------------------------------------------------------------------------------------------------------------------------------
                    elif re.search("(너|네|니)", transcript) and re.search("(말|대화|상담|얘기)", transcript):
                        naver_tts("나도 좋아! 무슨 일 있었니?", my_TwoWayClient)
                        my_TwoWayClient.ConversationFlag = True
                    # -------------------------------------------------------------------------------------------------------------------------------------


                elif my_TwoWayClient.MynameFlag == False: # 절전/대기 모드
                    if re.search(str(my_TwoWayClient.myname), transcript) or re.search(str(my_TwoWayClient.nickname), transcript):
                        naver_tts("불렀니?", my_TwoWayClient)
                        my_TwoWayClient.MynameFlag = True # 활성화 모드로 전환
                    #-------------------------------------------------------------------------------------------------------------------------------------
                    elif re.search("(나|너|당신|네)", transcript) and re.search("(이름)", transcript) and re.search("(뭐|모|무엇|누구)", transcript):
                        naver_tts("내 이름은 " + my_TwoWayClient.myname + " 이라고 해!", my_TwoWayClient)

                    elif re.search("(이름)", transcript) and re.search("(바꾸|바꿔|바꿀)", transcript):
                        naver_tts("내 새로운 이름을 불러줘!", my_TwoWayClient)
                        my_TwoWayClient.CreateNameFlag = True

                    elif re.search("(완전 종료)", transcript):
                        sys.stdout.write(WHITE)  # 하얀색 옵션
                        naver_tts("완전 종료를 실시합니다.", my_TwoWayClient)
                        sys.stdout.write("종료 중...\n")  # 종료 중... 출력
                        my_TwoWayClient.ClosedFlag = True
                        stream.closed = True  # stream의 중지 closed = True
                        break  # for문 탈출 } }
                    #-------------------------------------------------------------------------------------------------------------------------------------



            # Exit recognition if any of the transcribed phrases could be
            # one of our keywords.
            # if re.search(r"\b(exit|quit)\b", transcript, re.I):

        if not result.is_final: # result의 is_final이 False일 경우 {
            sys.stdout.write(RED) # 빨간색 옵션
            sys.stdout.write("\033[K") # clear line
            sys.stdout.write(str(corrected_time) + ": " + transcript + "\r") # "정정시간 : 번역 문장" 출력

            stream.last_transcript_was_final = False # stream의 마지막 번역이 최종 = False } }

def power_saving_mode(my_TwoWayClient, sio):
    while True:
        if my_TwoWayClient.ClosedFlag == True or my_TwoWayClient.LimitTimeFlag == True:
            my_TwoWayClient.LimitTimeFlag = False
            sio.disconnect()
            break

        else:
            if my_TwoWayClient.MynameFlag == True:
                sys.stdout.write(WHITE)  # 하얀색 옵션
                print("활성화 상태입니다.")
                while (my_TwoWayClient.limit_time != 0):
                    if my_TwoWayClient.MynameFlag == False or my_TwoWayClient.ClosedFlag == True:
                        break
                    if my_TwoWayClient.ListeningFlag == False:
                        my_TwoWayClient.limit_time = 30
                    elif my_TwoWayClient.ListeningFlag == True:
                        my_TwoWayClient.limit_time = my_TwoWayClient.limit_time - 1
                        time.sleep(1)
                        if my_TwoWayClient.limit_time <= 5 :
                            sys.stdout.write(WHITE)  # 하얀색 옵션
                            print("절전 모드 진입까지 : ", my_TwoWayClient.limit_time, "초")

                if my_TwoWayClient.limit_time == 0:
                    naver_tts("절전모드로 변경할게! 언제든 다시 불러줘!", my_TwoWayClient)

                my_TwoWayClient.MynameFlag = False

                my_TwoWayClient.CreateNameFlag = False
                my_TwoWayClient.MygenderFlag = False
                my_TwoWayClient.ConversationFlag = False
                my_TwoWayClient.PlayFlag = False

            elif my_TwoWayClient.MynameFlag == False:
                my_TwoWayClient.limit_time = 30
                time.sleep(3)
                sys.stdout.write(WHITE)  # 하얀색 옵션
                print("절전/대기 상태입니다.")

# main문 시작
def main(my_TwoWayClient, sio):
    """start bidirectional streaming from microphone input to speech API"""
    client = speech.SpeechClient() # client = Google Cloud Speech API 객체
    config = speech.RecognitionConfig( # config = Recognizer process 객체
        encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16, # 인코딩 된 오디오 데이터가 RecognitionAudio로 전송
        sample_rate_hertz=SAMPLE_RATE, # sampling rate
        language_code="ko-KR", # 언어 코드
        enable_automatic_punctuation=True,
        use_enhanced=True,
        max_alternatives=1, # 반환할 인식 가설의 최대 수
    )

    streaming_config = speech.StreamingRecognitionConfig( # streaming_config = 요청 처리하는 방법을 지정하는 정보 객체
        config=config, interim_results=True # config, interim_result(is_final=true 결과만 반환)
    )

    # naver_tts("안녕하세요, 제 이름은 " + my_TwoWayClient.myname + "이라고 해요. 만나서 반가워요!", my_TwoWayClient)

    mic_manager = ResumableMicrophoneStream(SAMPLE_RATE, CHUNK_SIZE) # mic_manager = ResumableMicrophoneStream 객체
    sys.stdout.write(YELLOW) # 노란색 옵션
    sys.stdout.write('\n듣는 중... 중단하려면 "완전 종료" 라고 말해주세요.\n\n')
    sys.stdout.write("=====================================================\n")
    sys.stdout.write(WHITE)  # 하얀색 옵션

    with mic_manager as stream: # mic_manager에서 stream이라는 객체 생성 {

        while not stream.closed: # stream의 중단 closed가 True가 아닐 때까지 반복 {

            sio.connect(host, namespaces=['/realchat'])
            sys.stdout.write(YELLOW) # 노란색 옵션
            sys.stdout.write(                                                   
                "\n" + str(STREAMING_LIMIT * stream.restart_counter) + ": NEW REQUEST\n"
            ) # "(4분 * stream의 재시작 카운터) : NEW REQUEST" 출력

            stream.audio_input = [] # stream의 오디오 입력 list 선언

            audio_generator = stream.generator(my_TwoWayClient) # audio_generator = stream의 제너레이터 실행 -> yield에 저장된 data list 저장

            requests = (
                speech.StreamingRecognizeRequest(audio_content=content)
                for content in audio_generator
            )  # requests = audio_generator에 저장된 data list를 content로 순서대로 저장

            responses = client.streaming_recognize(streaming_config, requests) # responses = 양방향 스트리밍 음성 인식 수행 -> 요청된 응답 저장

            # Now, put the transcription responses to use.

            format = "%(asctime)s: %(message)s"
            logging.basicConfig(format=format, level=logging.INFO, datefmt="%H:%M:%S")
            thread = Thread(target=power_saving_mode, args=(my_TwoWayClient,sio,))
            thread.start()
            logging.info("스레드 시작")

            listen_print_loop(responses, stream, my_TwoWayClient, sio) # listen_print_loop 함수 통해 stt 내용 출력

            thread.join()
            logging.info("Exiting")

            if stream.result_end_time > 0: # stream의 결과 끝시간이 0보다 클 경우 {
                stream.final_request_end_time = stream.is_final_end_time # stream의 최종 요청 끝시간 = stream의 최종 끝시간 }
            stream.result_end_time = 0 # stream의 결과 끝시간 초기화
            stream.last_audio_input = [] # stream의 마지막 오디오 입력 list 초기화
            stream.last_audio_input = stream.audio_input # stream의 마지막 오디오 입력 = stream의 오디오 입력
            stream.audio_input = [] # stream의 오디오 입력 list 초기화
            stream.restart_counter = stream.restart_counter + 1 # stream의 재시작 카운터 = stream의 재시작 카운터 + 1

            if not stream.last_transcript_was_final: # stream의 마지막 번역 최종이 True가 아닐 경우 {
                sys.stdout.write("\n") # 한줄 Enter }
            stream.new_stream = True # stream의 새 stream = True --> generator 실행 } }

if __name__ == "__main__": # main() 실행
    main()
