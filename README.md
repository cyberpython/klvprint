klvprint
========


## Description

klvprint is a small Python program that utilizes FFmpeg to extract KLV data 
embedded in MPEG-TS video files or streams and then prints them to stdout in
plain text, CSV or JSON format.

## Requirements

Python 3.x with pip (tested with Python 3.10 on Ubuntu 22.04.1).

FFmpeg (tested with 4.4.2 on Ubuntu 22.04.1).

All other required dependencies can be installed using pip with:

```
pip3 install -r requirements.txt
```

## Usage

Run with:

```
python3 klvprint.py [-h] [-o {text,csv,json}] [-m MAP] input
```

The `-h` / `--help` flag causes a help message to be displayed.

The only required argument is `input` which defines the MPEG-TS video file path or stream URL.

The `-o` / `--output` flag controls the type of output (plain text / CSV / JSON). Default is plain text.

The `-m` / `--map` flag can be used to define the substream for KLV data in the video stream. It should be in the format FFmpeg uses (usually 0:1 for a single MPEG-TS stream with KLV metadata built into it).

### Examples

Extract KLV data from a file, use ffprobe to detect the KLV metadata index in the stream and print the KLV data in plain text to stdout:

```
python3 klvcat.py samples/Night\ Flight\ IR.mpg
```

Extract KLV data from an MPEG-TS stream (udp://127.0.0.1:12345), explicitly define the KLV metadata index in the stream as 0:1 and output the KLV data as JSON in a file:

```
python3 klvcat.py -m 0:1 -o JSON udp://127.0.0.1:12345 > klv.json
```

To test stream decoding, you can use FFmpeg to stream an MPEG-TS file with embedded KLV metadata as follows:

```
ffmpeg -re -i <video_file> -map 0 -c copy -f mpegts <stream_URL>
```

e.g.:

```
ffmpeg -re -i samples/Night\ Flight\ IR.mpg -map 0 -c copy -f mpegts udp://127.0.0.1:1234
```

## Acknowledgements

This would not have been possible without the awesome:

- FFmpeg(https://www.ffmpeg.org/) application (LGPL 2.1 license)
- klvdata (https://github.com/paretech/klvdata) library (MIT license)
- ffmpeg-python (https://github.com/kkroening/ffmpeg-python) library (Apache-2.0 license)
