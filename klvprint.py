#!/usr/bin/env python3

# MIT License
# 
# Copyright (c) 2024 Georgios Migdos
# 
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
# 
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
# 
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

import argparse
import codecs
import json
import sys
import threading
from queue import Queue, Empty
import time
from typing import BinaryIO

import ffmpeg
import klvdata


def detect_klv_stream_index(stream_url):
    """Use ffmpeg.probe to find the KLV metadata stream index"""
    try:
        probe = ffmpeg.probe(stream_url, loglevel="quiet")
        for stream in probe["streams"]:
            if stream.get("codec_type") == "data" and "klv" in stream.get(
                "codec_name", ""
            ):
                return f'0:{stream["index"]}'
    except ffmpeg.Error:
        return None
    except KeyboardInterrupt:
        return None
    return None


class KlvPacketReader(threading.Thread):

    def __init__(
        self,
        src: BinaryIO,
        output_queue: Queue,
        klv_header_size=16,
        klv_sync_pattern=b"\x06\x0e+4",
    ):
        super().__init__(name="KlvPacketReader")
        self._src = src
        self._output_queue = output_queue
        self._klv_sync_pattern = klv_sync_pattern
        self._klv_header_size = klv_header_size
        self._stopped = threading.Event()

    def stop(self):
        self._stopped.set()

    def _read(self, src: BinaryIO, num_bytes, buffer):

        data = src.read(num_bytes)

        return data, buffer + data

    def _read_value(self, src, num_bytes, buffer):

        data = src.read(num_bytes)

        return ord(data), buffer + data

    def _read_ber(self, src, buffer):

        byte_length, buffer = self._read_value(src, 1, buffer)  # reads BER byte

        if byte_length < 128:
            length = byte_length
        else:
            length, buffer = self._read_value(src, byte_length - 128, buffer)

        _, buffer = self._read(src, length, buffer)

        return buffer

    def run(self):

        klv_sync_pattern_length = len(self._klv_sync_pattern)
        klv_header_excl_sync = self._klv_header_size - klv_sync_pattern_length

        while not self._stopped.is_set():
            # Init empty buffer:
            buffer = b""

            # Read sync pattern:
            header, buffer = self._read(self._src, klv_sync_pattern_length, buffer)

            if header == self._klv_sync_pattern:
                # Read rest of the header:
                _, buffer = self._read(self._src, klv_header_excl_sync, buffer)
                # Read BER-encoded data:
                buffer = self._read_ber(self._src, buffer)
                # Place data into the queue:
                self._output_queue.put(buffer)


class KlvOutputWriter:

    def start(self, out: BinaryIO):
        pass
    
    def start_entry(self, out: BinaryIO, entry_index):
        pass

    def write_item(self, out: BinaryIO, tag, item, entry_index, item_index):
        pass

    def end_entry(self, out: BinaryIO, entry_index):
        pass

    def end(self, out: BinaryIO):
        pass


class KlvTextOutputWriter(KlvOutputWriter):

    def start_entry(self, out: BinaryIO, entry_index):
        out.write(f"> KLV Packet #{entry_index}\n")

    def write_item(self, out: BinaryIO, tag, item, entry_index, item_index):
        LDSName, ESDName, UDSName, value = item
        out.write(f"\t [{tag}] {LDSName}: {value}\n")


class KlvCsvOutputWriter(KlvOutputWriter):

    def start(self, out):
        out.write(f"#,tag,field,value\n")

    def write_item(self, out: BinaryIO, tag, item, entry_index, item_index):
        LDSName, ESDName, UDSName, value = item
        out.write(f"{entry_index},{tag},{LDSName},{value}\n")


class KlvJsonOutputWriter(KlvOutputWriter):

    def start(self, out):
        out.write("[\n")

    def end(self, out):
        out.write("]\n")
        out.flush()

    def start_entry(self, out, entry_index):
        if entry_index > 1:
            out.write(',\n')
        out.write('\t{\n\t\t"items": [\n')

    def _to_hex_str(self, value):
        if len(value) < 3:
            return ""
        input_str = value[2:-1]
        byte_data = codecs.decode(input_str, 'unicode_escape').encode('latin1')
        return f'"{"".join(f"{byte:02x}" for byte in byte_data)}"'

    def write_item(self, out: BinaryIO, tag, item, entry_index, item_index):
        LDSName, ESDName, UDSName, value = item
        if item_index > 1:
            out.write(", \n")
        out.write(f'\t\t\t{{\n')
        out.write(f'\t\t\t\t"tag": {json.dumps(tag)},\n')
        out.write(f'\t\t\t\t"field": {json.dumps(LDSName)},\n')
        out.write(f'\t\t\t\t"value": { self._to_hex_str(value) if tag == 1 else json.dumps(value)}\n')
        out.write(f'\t\t\t}}')

    def end_entry(self, out, entry_index):
        out.write('\n\t\t]\n\t}')


class KlvPrinter(threading.Thread):

    def __init__(self, input_queue: Queue, writer: KlvOutputWriter, out: BinaryIO):
        threading.Thread.__init__(self, name="KlvPrinter")
        self.q = input_queue
        self.writer = writer
        self.out = out
        self.stopped = threading.Event()

    def stop(self):
        self.stopped.set()

    def run(self) -> None:
        packet_count = 0
        self.writer.start(self.out)
        while not self.stopped.is_set():
            try:
                buffer = self.q.get(timeout=1.0)
                for packet in klvdata.StreamParser(buffer):
                    packet_count += 1
                    metadata = packet.MetadataList()
                    self.writer.start_entry(self.out, packet_count)
                    # print(f"> KLV Packet #{i}")
                    item_count = 0
                    for tag, item in metadata.items():
                        item_count += 1
                        try:
                            self.writer.write_item(self.out, tag, item, packet_count, item_count)                            
                        except KeyError:
                            pass
                    self.writer.end_entry(self.out, packet_count)
            except Empty:
                continue
        self.writer.end(self.out)







if __name__ == "__main__":

    parser = argparse.ArgumentParser(description="Extract and output KLV metadata from video or stream. Requires FFmpeg to be on the PATH.")
    parser.add_argument("input", help="Path to video file or stream URL.")
    parser.add_argument("-o", "--output", choices=['text', 'csv', 'json'], default='text',
                        help="Output format: plain text, CSV, or JSON (default: plain text).")
    parser.add_argument("-m", "--map", default=None, help="Optional FFmpeg -map parameter value for the KLV data stream (the stream identifier, e.g. '0:1'). If missing, ffprobe will be used to detect the correct stream for KLV data.")
    args = parser.parse_args()


    input_stream_url = args.input
    klv_stream_index = args.map if args.map is not None else detect_klv_stream_index(input_stream_url)

    if klv_stream_index is None:
        print("Could not detect KLV stream index! Exiting.", file=sys.stderr)
        sys.exit(1)
    else:

        stream = ffmpeg.input(f"{input_stream_url}")
        stream = ffmpeg.output(
            stream,
            "pipe:",
            map=klv_stream_index,
            codec="copy",
            format="data",
            flush_packets=1,
            loglevel="quiet",
        )
        ffmpeg_proc = ffmpeg.run_async(stream, pipe_stdout=True, pipe_stdin=False)

        data_queue = Queue()

        writer = None
        if args.output == 'json':
            writer = KlvJsonOutputWriter()
        elif args.output == 'csv':
            writer = KlvCsvOutputWriter()
        elif args.output == 'text':
            writer = KlvTextOutputWriter()

        klvPrinter = KlvPrinter(data_queue, writer, sys.stdout)
        klv_packet_reader = KlvPacketReader(ffmpeg_proc.stdout, data_queue)

        klvPrinter.start()
        klv_packet_reader.start()

        try:
            while ffmpeg_proc.poll() is None:
                time.sleep(1)
        except KeyboardInterrupt:
            pass

        klv_packet_reader.stop()
        klvPrinter.stop()
        ffmpeg_proc.kill()

        klv_packet_reader.join()
        klvPrinter.join()
        ffmpeg_proc.wait()
