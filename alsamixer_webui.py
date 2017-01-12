#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# File:    alsamixer_webui.py
# Date:    24. 1. 2016
# Author:  Jiri Skorpil <jiri.sko@gmail.com>
# Desc.:   ALSA Mixer WebUI - main application
#

import sys
import re
import os
import errno
from subprocess import call, Popen, PIPE
import socket
import json
from flask import Flask, Response
import argparse

import pickle
try:
    # Python 2.x
    import ConfigParser
except ImportError:
    # Python 3.x
    import configparser as ConfigParser


CONFIG_FILE = '/etc/amixer-webui.conf'
DEFAULT_HOST = '0.0.0.0'
DEFAULT_PORT = '8080'


class Handler(Flask):

    card = None
    equal = False

    PULSE_AUDIO_DEVICE_NUMBER = 99999

    def __init__(self, *args, **kwargs):
        Flask.__init__(self, *args, **kwargs)

    def __get_amixer_command__(self):
        command = ["amixer"]
        if self.card == self.PULSE_AUDIO_DEVICE_NUMBER:
            command += ["-D", "pulse"]
        elif self.card is not None:
            command += ["-c", "%d" % self.card]
        if self.equal is True:
            command += ["-D", "equal"]
        return command

    @staticmethod
    def __get_channel_name__(desc, name, i):
        for control in desc:
            lines = control.split("\n")
            control_name = re.sub("',[0-9]+", "", lines[0][1:])
            if control_name not in name:
                continue

            for line in lines[1:]:
                if name.split(" ")[-2] in line:
                    names = line.split(": ")[1].split(" - ")
                    return names[i]

        return None

    def __get_cards__(self):
        system_cards = []
        try:
            with open("/proc/asound/cards", 'rt') as f:
                for l in f.readlines():
                    if ']:' in l:
                        system_cards.append(l.strip())
        except IOError as e:
            if e.errno != errno.ENOENT:
                raise e

        cards = {}
        for i in system_cards:
            card_number = i.split(" [")[0].strip()
            card_detail = Popen(["amixer", "-c", card_number, "info"], stdout=PIPE).communicate()[0]
            cards[card_number] = self.__decode_string(card_detail).split("\n")[1].split(":")[1].replace("'", "").strip()

        pulse = Popen(["amixer", "-D", "pulse", "info"], stdout=PIPE)
        pulse.communicate()
        if pulse.wait() == 0:
            cards[self.PULSE_AUDIO_DEVICE_NUMBER] = "PulseAudio"

        return cards

    def __get_controls__(self):
        try:
            amixer_contents = self.__decode_string(
                Popen(self.__get_amixer_command__() + ["scontents","-M"], stdout=PIPE).communicate()[0])
        except OSError:
            return []

        interfaces = []
        if self.equal:
           self.equal_idx=[]
        else:
           self.standard_idx=[]
        co=0
        for i in amixer_contents.split("Simple mixer control")[1:]:
            lines = i.split("\n")

            interface = {
                "id": co, #int(lines[0].split(",")[0]),
                "iface": u"MIXER", #lines[0].split(",")[1].replace("iface=", ""),
                "name": lines[0].split("'")[1], # lines[0].split(",")[2].replace("name=", "").replace("'", ""),
                "type": lines[1].split()[1], #lines[1].split(",")[0].replace("  ; type=", ""),
                "access": u"rw------", #lines[1].split(",")[1].replace("access=", ""),
            }

            if interface["type"] == "enum":
                interface["type"]=u'ENUMERATED'
                items = {}
                for  idx, val in enumerate(lines[2].split("'")[1::2]):
                    items[str(idx).decode('utf8')] = val
                interface["items"] = items
                interface["values"] = []
                for val in lines[3].split("'")[1::2]:
                    interface["values"].append(int( items.keys()[items.values().index(val)] ))

            elif "switch" in interface["type"]:
                interface["type"]=u'BOOLEAN'
                interface["values"] = []
                for line in lines[2:]:
                    if '[on]' in line: interface["values"].append(True)
                    if '[off]' in line: interface["values"].append(False)

            elif "volume" in interface["type"]:
                interface["type"]=u'INTEGER'
                interface["step"] = 0

                interface["values"] = []
                interface["channels"] = []
                for line in lines[3:]:
                   if "Limits:" in line:
                      interface["max"]=int(line.split()[-1])
                      interface["min"]=int(line.split()[-3])
                   if '%]' in line:
                      interface["values"].append( re.findall('(\d+%)',line)[0][:-1] )
                      interface["channels"].append( line.split(':')[0].strip() )

            interfaces.append(interface)
            co+=1
            if self.equal:
               self.equal_idx.append(interface['name'])
            else:
               self.standard_idx.append(interface['name'])

#        if not self.equal:
#           fout=open('new.out','w')
#           pickle.dump(interfaces,fout)
#           fout.close()
        return interfaces

    def __get_equalizer__(self):
        self.equal = True
        data = self.__get_controls__()
        self.equal = False
        return data

    def __change_volume__(self, name, volumes_path):
        volumes = []
        for volume in volumes_path:
            if volume != "" and is_digit(volume):
                volumes.append(volume+'%')
        command = self.__get_amixer_command__() + ["set", name, ",".join(volumes),"-M"]
        call(command)

    @staticmethod
    def __decode_string(string):
        return string.decode("utf-8")


def is_digit(n):
    try:
        int(n)
        return True
    except ValueError:
        return False


app = Handler(__name__, static_folder='htdocs', static_url_path='')


@app.route('/')
def index():
    """Sends HTML file (GET /)"""
    f = open("index.tpl")
    html = f.read().replace("{$hostname}", socket.gethostname())
    f.close()
    return html


@app.route('/hostname/')
def get_hostname():
    """Sends server's hostname [plain text:String]"""
    return socket.gethostname()


@app.route('/cards/')
def get_cards():
    """Sends list of sound cards [JSON object - <number:Number>:<name:String>]"""
    data = json.dumps(app.__get_cards__())
    resp = Response(response=data, status=200, mimetype="application/json")
    return resp


@app.route('/card/')
def get_card():
    """Sends number of selected sound card [JSON - <Number|null>]"""
    data = json.dumps(app.card)
    resp = Response(response=data, status=200, mimetype="application/json")
    return resp


@app.route('/controls/')
def get_controls():
    """Sends list of controls of selected sound card [JSON - list of objects: {
    --- common keys ---
        access: <String>
        id: <Number>
        iface: <String>
        name: <String>
        type: <ENUMERATED|BOOLEAN|INTEGER:String>
    --- for type ENUMERATED ---
        items: <Object {<number:Number>:<name:String>}>
        values: [<Number> - selected item]
    --- for type BOOLEAN ---
        values: [true|false]
    --- for type INTEGER ---
        channels: <Array of String> - channel names
        min: <Number>
        max: <Number>
        step: <Number>
        values: <Array of Number> - channel values (order corresponds with order in `channels` key)
    }]"""
    data = json.dumps(app.__get_controls__())
    resp = Response(response=data, status=200, mimetype="application/json")
    print(resp)
    return resp


@app.route('/equalizer/')
def get_equalizer():
    """Sends list of equalizer controls [same as /controls/ but contains only controls of INTEGER type]"""
    data = json.dumps(app.__get_equalizer__())
    resp = Response(response=data, status=200, mimetype="application/json")
    return resp


@app.route('/control/<int:control_id>/<int:status>/', methods=['PUT'])
def put_control(control_id, status):
    """Turns BOOLEAN control on or off"""
    if control_id <= 0:
        return ''
    if status != 0 and status != 1:
        return ''
    call(app.__get_amixer_command__() + ["cset", "numid=%s" % control_id, "--", 'on' if status == 1 else 'off'])
    if os.geteuid() == 0:
        call(["alsactl", "store"])
    return ''


@app.route('/source/<int:control_id>/<int:item>/', methods=['PUT'])
def put_source(control_id, item):
    """Changes active ENUMERATED item"""
    if control_id <= 0:
        return ''
    call(app.__get_amixer_command__() + ["cset", "numid=%s" % control_id, "--", str(item)])
    if os.geteuid() == 0:
        call(["alsactl", "store"])
    return ''


@app.route('/volume/<int:control_id>/<path:volume_path>', methods=['PUT'])
def put_volume(control_id, volume_path):
    """Changes INTEGER channel volumes"""
    app.__change_volume__(app.standard_idx[control_id], volume_path.split('/'))
    if os.geteuid() == 0:
        call(["alsactl", "store"])
    return ''


@app.route('/equalizer/<int:control_id>/<path:level_path>', methods=['PUT'])
def put_equalizer(control_id, level_path):
    """Changes equalizer channel values"""
    app.equal = True
    card = app.card
    app.card = None
    app.__change_volume__(app.equal_idx[control_id], level_path.split('/'))
    app.equal = False
    app.card = card
    if os.geteuid() == 0:
        call(["alsactl", "store"])
    return ''


@app.route('/card/<int:card_id>/', methods=['PUT'])
def put_card(card_id):
    """Changes selected sound card"""
    app.card = card_id
    return ''


@app.after_request
def set_server_header(response):
    response.headers["Server"] = "ALSA Mixer webserver"
    return response


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-l", "--host", type=str)
    parser.add_argument("-p", "--port", type=int)
    parser.add_argument("-d", "--debug", action="store_true")
    args = parser.parse_args()

    if os.path.isfile(CONFIG_FILE):
        config = ConfigParser.RawConfigParser()
        config.read(CONFIG_FILE)

        if args.host is None:
            args.host = config.get('amixer-webui', 'host')

        if args.port is None:
            port = config.get('amixer-webui', 'port')
            if is_digit(port):
                args.port = int(port)

    if args.host == "":
        args.host = DEFAULT_HOST

    if args.port is None:
        args.port = DEFAULT_PORT

    app.run(**vars(args))

if __name__ == "__main__":

    main()

    sys.exit(0)

# end of alsamixer_webui.py
