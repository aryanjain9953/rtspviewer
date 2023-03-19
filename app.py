import os
import threading
import time

import cv2
import ffmpeg
from flask import Flask, render_template, Response, request, send_from_directory

app = Flask(__name__)
app.config['RECORDINGS_FOLDER'] = 'recordings'
lock = threading.Lock()
output_frame = None
vs = None
frame_size = None
recording = False
video_writer = None
rtsp_url = None


class VideoStream:
    def __init__(self, url):
        self.url = url
        self.capture = cv2.VideoCapture(url)
        self.lock = threading.Lock()

    def pause(self):
        with self.lock:
            self.capture.release()

    def resume(self):
        with self.lock:
            self.capture = cv2.VideoCapture(self.url)

    def read(self):
        with self.lock:
            return self.capture.read()


def rtsp_stream():
    global output_frame, lock, vs, recording, video_writer
    frame_counter = 0

    while True:
        try:
            if vs:
                ret, frame = vs.read()
                if not ret:
                    print("Failed to read frame")
                    continue

                frame_yuv = cv2.cvtColor(frame, cv2.COLOR_BGR2YUV_I420)

                if recording and video_writer is not None:
                    video_writer.stdin.write(frame_yuv.tobytes())
                    print("Writing frame to video file")
                    frame_counter += 1

                with lock:
                    output_frame = frame.copy()
            else:
                time.sleep(0.1)  # Add a small sleep to prevent high CPU usage
        except Exception as e:
            print("Exception in rtsp_stream: {}".format(e))
            break


def generate():
    global output_frame, lock
    while True:
        with lock:
            if output_frame is None:
                continue
            (flag, encodedImage) = cv2.imencode(".jpg", output_frame)
            if not flag:
                continue
        yield (b'--frame\r\n' b'Content-Type: image/jpeg\r\n\r\n' + bytearray(encodedImage) + b'\r\n')


@app.route('/')
def index():
    return render_template('index.html')


def construct_rtsp_url(brand, ip, username, password, rtsp_port, channel):
    if brand == "Hickvision":
        return f"rtsp://{username}:{password}@{ip}:{rtsp_port}/Streaming/Channels/{channel}"
    elif brand == "CP Plus":
        return f"rtsp://{username}:{password}@{ip}:{rtsp_port}/cam/realmonitor?channel={channel}&subtype=0"
    elif brand == "Uniview":
        return f"rtsp://{username}:{password}@{ip}:{rtsp_port}/unicast/c{channel}/s0/live"
    elif brand == "Dahua":
        return f"rtsp://{username}:{password}@{ip}:{rtsp_port}/cam/realmonitor?channel={channel}&subtype=0"
    elif brand == "Securus":
        # Replace this with the appropriate RTSP URL format for Securus
        return f"rtsp://{username}:{password}@{ip}:{rtsp_port}/some_path/{channel}"
    elif brand == "Securens":
        # Replace this with the appropriate RTSP URL format for Securens
        return f"rtsp://{username}:{password}@{ip}:{rtsp_port}/some_path/{channel}"
    else:
        return None


@app.route('/stream')
def video_feed():
    return Response(generate(), mimetype='multipart/x-mixed-replace; boundary=frame')


@app.route('/start_stream', methods=['POST'])
def start_stream():
    global vs, frame_size, rtsp_url
    brand = request.form['brand']
    ip = request.form['ip']
    username = request.form['username']
    password = request.form['password']
    rtsp_port = request.form['rtsp_port']

    for channel in range(1, 10000):
        channel_str = f"{channel:04d}"
        rtsp_url = construct_rtsp_url(brand, ip, username, password, rtsp_port, channel_str)
        print(f"Trying RTSP URL: {rtsp_url}")

        vs = VideoStream(rtsp_url)
        ret, _ = vs.read()
        if ret:
            print(f"Working RTSP URL: {rtsp_url}")
            break
        else:
            print(f"Failed RTSP URL: {rtsp_url}")
            vs = None

    frame_width = int(vs.capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    frame_height = int(vs.capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    frame_size = (frame_width, frame_height)
    return ('', 204)


@app.route('/pause_stream', methods=['POST'])
def pause_stream():
    global vs
    if vs:
        vs.pause()
    return ('', 204)


@app.route('/resume_stream', methods=['POST'])
def resume_stream():
    global vs
    if vs:
        vs.resume()
    return ('', 204)


@app.route('/start_recording', methods=['POST'])
def start_recording():
    global video_writer, recording, frame_size
    if not os.path.exists(app.config['RECORDINGS_FOLDER']):
        os.makedirs(app.config['RECORDINGS_FOLDER'])

    filename = os.path.join(app.config['RECORDINGS_FOLDER'], 'recording.mp4')
    fps = 20
    video_writer = (
        ffmpeg
            .input('pipe:', format='rawvideo', pix_fmt='yuv420p', s='{}x{}'.format(*frame_size), r=fps)
            .output(filename, format='mp4', pix_fmt='yuv420p', vcodec='libx264', r=fps, crf='23', preset='medium',
                    movflags='faststart')
            .overwrite_output()
            .run_async(pipe_stdin=True)
    )
    recording = True
    return ('', 204)


@app.route('/stop_recording', methods=['POST'])
def stop_recording():
    global video_writer, recording
    recording = False
    if video_writer:
        video_writer.stdin.close()
        video_writer.wait()
        video_writer = None
    return ('', 204)


@app.route('/download_recording')
def download_recording():
    return send_from_directory(app.config['RECORDINGS_FOLDER'], 'recording.mp4', as_attachment=True)


if __name__ == '__main__':
    t = threading.Thread(target=rtsp_stream)
    t.daemon = True
    t.start()
    app.run(debug=True, host='0.0.0.0', port=3000)
