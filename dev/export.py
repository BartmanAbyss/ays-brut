"""Export the whole intro as an MP4 - every frame, whatever the machine.

    python dev/export.py                      # build/intro.mp4: 4K render, 1080p60, 20 Mbit/s
    python dev/export.py --seconds 30 -o test.mp4
    python dev/export.py --no-open            # print the URL instead of opening a browser

Serves dev/ on 127.0.0.1 and opens the harness with ?export=1&show=1&det=1. det gives every
frame exactly one show step - what the release takes at a steady 60 fps - and the page
starts the next frame only after this one is read back and sent here, so the export never
skips a frame or a simulation step: a slow GPU only makes it take longer. The page renders
at --render (3840x2160), scales each frame down to --size (1920x1080) on the GPU with the
lettering on top, converts it to BT.709 YUV 4:2:0 (NV12) there too, and sends it raw over a
WebSocket; this script pipes it into ffmpeg (libx264) with the soundtrack, which the page
renders first and sends as a WAV. Where the render is not a whole multiple of the video
(or with --cpu-scale) the page scales in a 2D canvas and sends RGBA instead, much slower.

Keep the browser window visible while it runs: the page does not depend on frame timing,
but a hidden tab may be throttled to a crawl. Needs ffmpeg on PATH, a WebGPU browser and
the websockets package (pip install websockets).
"""
import argparse
import functools
import http.server
import os
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import webbrowser

from websockets.sync.server import serve as ws_serve, ServerConnection   # pip install websockets

# The library reads the socket 64 KiB at a time and reassembles; for frames of 12-33 MB
# that was most of the export's time (33 MB: 86 ms at 64 KiB, 48 ms at 16 MiB).
ServerConnection.recv_bufsize = 16 << 20

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
FPS = 60   # the simulation's step rate: any other rate would not be the intro


def size(s):
    w, h = s.lower().split('x')
    return int(w), int(h)


class Export:
    def __init__(self, args):
        self.a = args
        self.ow, self.oh = args.size
        # what the page sends, which it says first: 'nv12' (scaled and converted on the
        # GPU, 12 bits a pixel) or 'rgba' (scaled in a 2D canvas, 32)
        self.fmt = None
        self.have_wav = False
        self.ff = None
        self.frames = 0
        self.t0 = None
        # where the time goes, from the second frame on: waiting for the page to render,
        # read back and send a frame, or blocked handing one to the encoder
        self.t_page = self.t_enc = 0.0
        self.lock = threading.Lock()
        self.done = threading.Event()
        self.error = None
        self.wav = os.path.join(tempfile.gettempdir(), 'comparade26-export.wav')
        self.log = os.path.splitext(args.out)[0] + '.ffmpeg.log'

    def start_ffmpeg(self):
        # The page's frame k shows show step k+1 (the first frame has already taken one
        # step), so the audio starts one frame in to line up with the picture.
        if self.fmt == 'nv12':
            # already BT.709 TV-range YUV 4:2:0 from the page: x264 takes NV12 as it is
            vin, vf = ['-pix_fmt', 'nv12', '-colorspace', 'bt709', '-color_range', 'tv'], []
        else:
            # RGB -> YUV with the BT.709 matrix, and tagged so: swscale defaults to BT.601,
            # which shifts the colours on every player that assumes 709 for HD
            vin, vf = ['-pix_fmt', 'rgba'], ['-vf', 'scale=out_color_matrix=bt709:out_range=tv,format=yuv420p']
        cmd = [self.a.ffmpeg, '-y', '-hide_banner', '-loglevel', 'warning',
               '-f', 'rawvideo', *vin, '-s', '%dx%d' % (self.ow, self.oh),
               '-framerate', str(FPS), '-i', '-',
               '-ss', '%.6f' % (1 / FPS), '-i', self.wav,
               '-map', '0:v', '-map', '1:a', *vf,
               '-colorspace', 'bt709', '-color_primaries', 'bt709', '-color_trc', 'bt709',
               '-color_range', 'tv',
               '-c:v', 'libx264', '-preset', self.a.preset, '-profile:v', 'high',
               '-b:v', self.a.bitrate, '-maxrate', self.a.maxrate, '-bufsize', self.a.bufsize,
               '-g', str(FPS), '-c:a', 'aac', '-b:a', '320k',
               '-movflags', '+faststart', '-shortest', self.a.out]
        self.ff = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=open(self.log, 'w'))

    def frame(self, data):
        with self.lock:
            if self.ff is None:
                if not self.have_wav:
                    raise RuntimeError('a frame arrived before the audio')
                if self.fmt not in ('nv12', 'rgba'):
                    raise RuntimeError('the page sent no pixel format (got %r)' % self.fmt)
                print('  frames as %s, encoding to %s' % (self.fmt.upper(), self.a.out))
                self.start_ffmpeg()
            want = self.ow * self.oh * 4 if self.fmt == 'rgba' else self.ow * self.oh * 3 // 2
            if len(data) != want:
                raise RuntimeError('frame %d is %d bytes, expected %d (%dx%d %s)'
                                   % (self.frames, len(data), want, self.ow, self.oh, self.fmt))
            self.ff.stdin.write(data)
            self.frames += 1
            if self.t0 is None:
                self.t0 = time.time()
            if self.frames % FPS == 0:
                el = time.time() - self.t0
                rate = self.frames / el if el else 0
                left = (self.total - self.frames) / rate if rate else 0
                print('\r  frame %5d / %d   show %6.2f s   %.1f fps   %d:%02d left   %s   '
                      % (self.frames, self.total, self.frames / FPS, rate, left // 60, left % 60,
                         self.split()), end='', flush=True)

    def split(self):
        n = max(self.frames - 1, 1)
        return 'page %.0f ms  encoder %.0f ms /frame' % (self.t_page / n * 1e3, self.t_enc / n * 1e3)

    def finish(self):
        with self.lock:
            self.ff.stdin.close()
            code = self.ff.wait()
        print()
        if code:
            self.error = 'ffmpeg exited with %d - see %s' % (code, self.log)
        self.done.set()


def ws_handler(ex):
    """The frames come over a WebSocket on the next port: the same 8 MB as a fetch() POST
    took the browser 150-500 ms to upload (curl: 4 ms), which made the upload, not the
    render, the export's speed. Each frame is acked once it is in the encoder."""
    def h(conn):
        try:
            acked = None
            for msg in conn:
                if isinstance(msg, str):   # the pixel format, before any frame
                    ex.fmt = msg
                    continue
                t1 = time.perf_counter()
                ex.frame(msg)
                t2 = time.perf_counter()
                if acked is not None:
                    ex.t_page += t1 - acked
                    ex.t_enc += t2 - t1
                conn.send('k')
                acked = time.perf_counter()
        except Exception as e:
            if not ex.done.is_set():   # a tab closed after the end is no failure
                ex.error = str(e)
                ex.done.set()
    return h


def handler(ex):
    class H(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def end_headers(self):
            self.send_header('Cache-Control', 'no-store')
            super().end_headers()

        def do_POST(self):
            path = urllib.parse.urlparse(self.path).path
            body = self.rfile.read(int(self.headers.get('Content-Length', 0)))
            try:
                if path == '/audio':
                    with open(ex.wav, 'wb') as f:
                        f.write(body)
                    print('  soundtrack received (%.1f MB)' % (len(body) / 1e6))
                    if not ex.total:   # the show plus its last second: 16-bit stereo 48 kHz
                        ex.total = int(round((len(body) - 44) / 4 / 48000 * FPS))
                    # ffmpeg starts with the first frame, once the page has said its format
                    ex.have_wav = True
                elif path == '/done':
                    ex.finish()
                elif path == '/fail':
                    ex.error = 'the page failed: ' + body.decode('utf-8', 'replace')
                    ex.done.set()
                else:
                    self.send_error(404)
                    return
            except Exception as e:   # tell the page, and stop
                ex.error = str(e)
                ex.done.set()
                self.send_error(500, str(e))
                return
            self.send_response(204)
            self.end_headers()
    return H


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('-o', '--out', default=os.path.join(ROOT, 'build', 'intro.mp4'))
    p.add_argument('--render', type=size, default=(3840, 2160), help='render size, WxH')
    p.add_argument('--size', type=size, default=(1920, 1080), help='video size, WxH')
    p.add_argument('--bitrate', default='20M')
    p.add_argument('--maxrate', default='30M')
    p.add_argument('--bufsize', default='40M')
    p.add_argument('--preset', default='slow', help='libx264 preset')
    p.add_argument('--ffmpeg', default=os.environ.get('FFMPEG', 'ffmpeg'),
                   help='the ffmpeg executable (default: $FFMPEG, else ffmpeg on PATH)')
    p.add_argument('--seconds', type=float, default=0,
                   help='stop at this show time (default: the end, plus a second of reverb)')
    p.add_argument('--port', type=int, default=8796, help='the page; the frames use the next one')
    p.add_argument('--no-open', action='store_true', help='print the URL, open nothing')
    p.add_argument('--cpu-scale', action='store_true',
                   help='scale in a 2D canvas, not on the GPU (slow; to compare the two)')
    a = p.parse_args()
    a.out = os.path.abspath(a.out)

    ex = Export(a)
    # the frame count, for progress only: the page decides when to stop
    # (without --seconds, set from the soundtrack's length when it arrives)
    ex.total = int(round(a.seconds * FPS))
    srv = http.server.ThreadingHTTPServer(('127.0.0.1', a.port),
                                          functools.partial(handler(ex), directory=HERE))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    # no compression (deflating 8 MB a frame costs far more than it saves on localhost)
    # and no size limit (the default is 1 MiB)
    wss = ws_serve(ws_handler(ex), '127.0.0.1', a.port + 1, compression=None, max_size=None)
    threading.Thread(target=wss.serve_forever, daemon=True).start()
    q = {'show': 1, 'det': 1, 'export': 1, 'w': a.render[0], 'h': a.render[1],
         'ow': a.size[0], 'oh': a.size[1]}
    if a.seconds:
        q['exportEnd'] = a.seconds
    if a.cpu_scale:
        q['exportCpu'] = 1
    url = 'http://localhost:%d/champagne.html?%s' % (a.port, urllib.parse.urlencode(q))
    print('exporting: %dx%d render -> %dx%d @ %d fps, %s' % (*a.render, *a.size, FPS, a.bitrate))
    print('  ' + url)
    if not a.no_open:
        webbrowser.open(url)
    try:
        ex.done.wait()
    except KeyboardInterrupt:
        ex.error = 'interrupted'
    srv.shutdown()
    wss.shutdown()
    if ex.ff and ex.ff.poll() is None:
        ex.ff.kill()
    if ex.error:
        print('EXPORT FAILED:', ex.error)
        sys.exit(1)
    el = time.time() - ex.t0 if ex.t0 else 0
    print('done: %s (%d frames, %.1f s, %.1f MB) in %d:%02d, %.1f fps; %s'
          % (a.out, ex.frames, ex.frames / FPS, os.path.getsize(a.out) / 1e6,
             el // 60, el % 60, ex.frames / el if el else 0, ex.split()))


if __name__ == '__main__':
    main()
