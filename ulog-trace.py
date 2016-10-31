# Copyright (C) 2016 by Aivars Kalvans <aivars.kalvans@gmail.com>
# 
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
# 
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
# 
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.

import sys
import re

from collections import defaultdict

import time
import subprocess

class Ulog:
    def __init__(self):
        self.config = subprocess.check_output(['tmunloadcf'])
        self.ulogpfx = self.config.split('ULOGPFX="')[-1].split('"')[0]
        self.fname = self._getname()
        try:
            self.fp = open(self.fname)
            self.fp.seek(0, 2)
        except:
            self.fb = None
        self.data = ''

    def _getname(self):
        return self.ulogpfx + '.' + time.strftime('%m%d%y', time.localtime())

    def _read(self):
        if not self.fp:
            self.fname = self._getname()
            try:
                self.fp = open(self.fname)
            except:
                return ''
        
        data = self.fp.read()
        if data:
            return data
        fname = self._getname()
        if self.fname != fname:
            self.fp = None

    def readline(self):
        n = self.data.find('\n')
        if n != -1:
            line = self.data[:n]
            self.data = self.data[n+1:]
            return line

        data = self._read()
        if data:
            self.data += data
            return self.readline()
        return None

    def readtrace(self):
        while True:
            line = self.readline()
            if line is None or 'TRACE:' in line:
                return line

class CallTiming:
    count = None
    errors = None
    total = None

    def __init__(self, count=0, total=0.0, errors=0):
        self.count = count
        self.total = total
        self.errors = errors

    def update(self, other):
        self.count += other.count
        self.total += other.total
        self.errors += other.errors

class ServiceTiming:
    count = 0
    errors = 0
    total = 0
    calls = None
    acalls = None

    def __init__(self):
        self.calls = {}
        self.acalls = {}

    def update(self, count, total, error, calls, acalls):
        self.count += count
        self.total += total
        self.errors += error
        for k, v in calls.items():
            try:
                self.calls[k].update(v)
            except KeyError:
                self.calls[k] = v
        for k, v in acalls.items():
            try:
                self.acalls[k].update(v)
            except KeyError:
                self.acalls[k] = v

class ServiceContext:
    name = None
    start_time = None
    end_time = None
    calls = None
    acalls = None
    error = 0

    call_name = None
    call_start_time = None

    def __init__(self, start_time, name):
        self.start_time = start_time
        self.name = name
        self.calls = {}
        self.acalls = {}

    def elapsed(self):
        return self.end_time - self.start_time
    def startCall(self, time, name):
        self.call_start_time = time
        self.call_name = 'svc:'+name
    def endCall(self, time):
        t = CallTiming(1, time - self.call_start_time)
        try:
            self.calls[self.call_name].update(t)
        except KeyError:
            self.calls[self.call_name] = t
    def endAcall(self, time):
        t = CallTiming(1, time - self.call_start_time)
        try:
            self.acalls[self.call_name].update(t)
        except KeyError:
            self.acalls[self.call_name] = t

class Collector:
    processes = {}
    timings = {}
    # When a trace record appears in the user log, the line looks like this:
    # hhmmss.system-name!process-name.pid: TRACE:cc:data
    # ULOGMILLISEC=Y; export ULOGMILLISEC
    re_trace = re.compile('(\d\d\d\d\d\d(\.\d\d\d)?).*!([^ ]+): .*TRACE:(at|ia): [ ]*([{}]) ([a-z]+)(.*)')
    re_service_name = re.compile('"(.+)"')

    def __init__(self):
        self.reset()

    def reset(self):
        self.timings = defaultdict(ServiceTiming)

    def parse_line(self, line):
        m = self.re_trace.match(line)
        if not m:
            return
        timestamp, _, process, _, enter_leave, func, params = m.groups()
        msec = self._parse_timestamp(timestamp)
        self.collect(msec, process, enter_leave, func, params)

    def _parse_timestamp(self, timestamp):
        """
        h, m, s = int(timestamp[0:2], 10), int(timestamp[2:4], 10), int(timestamp[4:6], 10)
        msec = ((((h * 60) + m) * 60) + s) * 1000
        msec += int('0' + timestamp[7:])
        """
        n = int(timestamp[:6], 10)
        h = n / 10000
        n = n % 10000
        m = n / 100
        s = n % 100
        msec = ((((h * 60) + m) * 60) + s) * 1000
        msec += int(timestamp[7:], 10)
        return msec

    def collect(self, msec, process, enter_leave, func, params):
        if enter_leave == '{':
            if func == 'tpservice':
                self.processes[process] = ServiceContext(msec, 'svc:'+self.re_service_name.search(params).group(1))
            elif func in ('tpcall', 'tpacall'):
                try:
                    self.processes[process].startCall(msec, self.re_service_name.search(params).group(1))
                except KeyError:
                    self.processes[process] = ServiceContext(msec, 'proc:'+process.split('.')[0])
                    self.processes[process].startCall(msec, self.re_service_name.search(params).group(1))
            elif func == 'tpreturn':
                # TPSUCCESS == 2
                if not params.startswith('(2, '):
                    try:
                        self.processes[process].error = 1
                    except KeyError:
                        pass

        elif enter_leave == '}':
            if func == 'tpservice':
                ctx = self.processes[process]
                del self.processes[process]
                ctx.end_time = msec
                self.timings[ctx.name].update(1, ctx.elapsed(), ctx.error, ctx.calls, ctx.acalls)
            elif func == 'tpcall':
                try: self.processes[process].endCall(msec)
                except KeyError: pass
            elif func == 'tpacall':
                try: self.processes[process].endAcall(msec)
                except KeyError: pass

    def finalize(self):
        for process, ctx in self.processes.items():
            self.timings[ctx.name].update(0, 0, 0, ctx.calls, ctx.acalls)
        return self.timings

def collect_timings(tracefile):
    c = Collector()

    for line in open(tracefile).xreadlines():
        c.parse_line(line)

    return c.finalize()

def do_service_graph(tracefile, outfile):
    try:
        import pydot
    except ImportError:
        sys.exit('Error: Module pydot not found for service graph output')
        

    timings = collect_timings(tracefile)

    graph = pydot.Dot('tmtrace', graph_type='digraph') 

    nodes = {}
    def graph_node(name):
        try:
            return nodes[name]
        except KeyError:
            if name.startswith('proc:'):
                n = pydot.Node(name.replace(':', '_'), shape='box', label=name.split(':')[-1])
            else:
                n = pydot.Node(name.replace(':', '_'), label=name.split(':')[-1])
            nodes[name] = n
            graph.add_node(n)
            return n

    for name, timing in timings.items():
        n = graph_node(name)
        for call in timing.calls:
            graph.add_edge(pydot.Edge(n, graph_node(call)))
        for call in timing.acalls:
            graph.add_edge(pydot.Edge(n, graph_node(call), style='dashed'))

    graph.write(outfile, format=outfile[outfile.rindex('.')+1:])

def do_service_timing(tracefile):
    timings = collect_timings(tracefile)

    array = [(name.split(':')[-1], timing.count, timing.total, timing.errors, timing.calls.items(), timing.acalls.items()) \
            for  name, timing in timings.items() if name.startswith('svc:')]
    array.sort(key=lambda x:x[2])

    print('Service                         Count/Errors  Time')
    print('------------------------------------------------------')
    for name, count, total, errors, calls, acalls in reversed(array):
        print('%-26s     %6d/%-6d  %f' % (name, count, errors, long(total)/1000.))
        childs = []
        childs += [('tpcall(%s)' % name.split(':')[-1], timing.count, timing.total) for name, timing in calls]
        childs += [('tpacall(%s)' % name.split(':')[-1], timing.count, timing.total) for name, timing in acalls]

        # Sort by timing.total (descending)
        childs.sort(key=lambda x:-x[2])
        for name, count, total in childs:
            print('    %-26s %6d         %f' % (name, count, long(total)/1000.))

def do_report(send):
    import urllib
    import json

    c = Collector()
    ulog = Ulog()

    interval = 60
    finish = time.time() + interval
    while True:

        # Collect data for specified interval
        while time.time() < finish:
            line = ulog.readtrace()
            if line is None:
                time.sleep(0.1)
            else:
                c.parse_line(line)

        finish += interval
        timings = c.timings
        c.reset()

        array = [(name.split(':')[-1], timing.count, timing.total, timing.errors, timing.calls.items(), timing.acalls.items()) \
                for  name, timing in timings.items() if name.startswith('svc:')]
        send(array)

def main():
    from optparse import OptionParser
    parser = OptionParser(usage='Usage: %prog [options]', version='%prog 1.0')
    parser.add_option('-G', '--graph',
            dest='graph',
            help='Produce service call graph')
    parser.add_option('--appdynamics',
            dest='appdynamics',
            help='Report to AppDynamics')
    parser.add_option('--graphite',
            dest='graphite',
            help='Report to Graphite')
    parser.add_option('-T', '--timing',
            dest='timing',
            help='Produce service timings')
    parser.add_option('-O', '--output',
            dest='out',
            help='Output file name (.dot or .png for service call graph)')

    (options, args) = parser.parse_args()

    if len([fmt for fmt in (options.graph, options.timing, options.appdynamics, options.graphite) if fmt]) > 1:
        parser.error('Please select only one output type')
    

    if options.graph and not options.out:
        parser.error('Please specify an output filename with "-O file.png" or "--output=file.png"')

    if options.graph:
        do_service_graph(options.graph, options.out)
    elif options.timing:
        do_service_timing(options.timing)
    elif options.appdynamics:
        def send(array):
            metrics = []
            for name, count, total, errors, calls, acalls in reversed(array):
                metrics.extend([
                    {
                        'metricName': 'Custom Metrics|Tuxedo|' + 'Services|%s|Number of Calls' % name,
                        'aggregatorType': 'SUM',
                        'value': count,
                    }, {
                        'metricName': 'Custom Metrics|Tuxedo|' + 'Services|%s|Failures' % name,
                        'aggregatorType': 'SUM',
                        'value': errors,
                    }, {
                        'metricName': 'Custom Metrics|Tuxedo|' + 'Services|%s|Total Time (msec)' % name,
                        'aggregatorType': 'SUM',
                        'value': total-sum([timing.total for _, timing in calls+acalls]),
                    }, {
                        'metricName': 'Custom Metrics|Tuxedo|' + 'Services|%s|Cumulative Time (msec)' % name,
                        'aggregatorType': 'SUM',
                        'value': total,
                    }
                ])

            try:
                urllib.urlopen(options.appdynamics, json.dumps(metrics))
                print 'Reported %d metrics' % (len(metrics))
            except IOError, e:
                print e

        do_report(send)
    elif options.graphite:
        def send(array):
            metrics = []
            now = int(time.time())
            for name, count, total, errors, calls, acalls in reversed(array):
                name = name.replace('.', '_')
                metrics.append('Tuxedo.Services.%s.calls %f %d' % (name, count, now))
                metrics.append('Tuxedo.Services.%s.errors %f %d' % (name, errors, now))
                metrics.append('Tuxedo.Services.%s.tottime %f %d' % (name, total-sum([timing.total for _, timing in calls+acalls]), now))
                metrics.append('Tuxedo.Services.%s.cumtime %f %d' % (name, total, now))

            try:
                from socket import socket
                sock = socket()
                host, port= options.graphite.split(':')
                sock.connect((host, int(port)))
                sock.sendall('\n'.join(metrics) + '\n')
                print 'Reported %d metrics' % (len(metrics))
            except IOError, e:
                print e


        do_report(send)
    else:
        parser.error('No output type selected')

if __name__ == '__main__':
    main()
