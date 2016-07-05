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

# When a trace record appears in the user log, the line looks like this:
# hhmmss.system-name!process-name.pid: TRACE:cc:data
# ULOGMILLISEC=Y; export ULOGMILLISEC
re_trace = re.compile('(\d\d\d\d\d\d(\.\d\d\d)?).*!([^ ]+): .*TRACE:(at|ia): [ ]*([{}]) ([a-z]+)(.*)')

def read_tmtrace(tracefile):
    for line in open(tracefile).xreadlines():
        line = line.rstrip()
        m = re_trace.match(line)
        if not m:
            continue
        seconds, _, process, _, enter_leave, func, params = m.groups()
        msec = ((int(seconds[0:2]) * 60 * 60) + (int(seconds[2:4]) * 60) + int(seconds[4:6])) * 1000
        msec += int('0' + seconds[7:])
        yield (msec, process, enter_leave, func, params)

class Timing:
    count = None
    total = None

    def __init__(self, count=0, total=0.0):
        self.count = count
        self.total = total

    def update(self, other):
        self.count += other.count
        self.total += other.total

class ServiceTiming(Timing):
    calls = None
    acalls = None

    def __init__(self, count, total, calls, acalls):
        Timing.__init__(self, count, total)
        self.calls = dict(calls)
        self.acalls = dict(acalls)

    def update(self, count, total, calls, acalls):
        self.count += count
        self.total += total
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
        t = Timing(1, time - self.call_start_time)
        try:
            self.calls[self.call_name].update(t)
        except KeyError:
            self.calls[self.call_name] = t
    def endAcall(self, time):
        t = Timing(1, time - self.call_start_time)
        try:
            self.acalls[self.call_name].update(t)
        except KeyError:
            self.acalls[self.call_name] = t

def collect_timings(tracefile):
    processes = {}
    timings = {}

    re_service_name = re.compile('"(.+)"')
    for x in read_tmtrace(tracefile):
        if x:
            msec, process, enter_leave, func, params = x
            if enter_leave == '{':
                if func == 'tpservice':
                    processes[process] = ServiceContext(msec, 'svc:'+re_service_name.search(params).group(1))
                elif func in ('tpcall', 'tpacall'):
                    try:
                        processes[process].startCall(msec, re_service_name.search(params).group(1))
                    except KeyError:
                        processes[process] = ServiceContext(msec, 'proc:'+process.split('.')[0])
                        processes[process].startCall(msec, re_service_name.search(params).group(1))

            elif enter_leave == '}':
                if func == 'tpservice':
                    ctx = processes[process]
                    del processes[process]
                    ctx.end_time = msec
                    try:
                        timings[ctx.name].update(1, ctx.elapsed(), ctx.calls, ctx.acalls)
                    except KeyError:
                        timings[ctx.name] = ServiceTiming(1, ctx.elapsed(), ctx.calls, ctx.acalls)
                elif func == 'tpcall':
                    processes[process].endCall(msec)
                elif func == 'tpacall':
                    processes[process].endAcall(msec)

    for process, ctx in processes.items():
        try:
            timings[ctx.name].update(0, 0, ctx.calls, ctx.acalls)
        except KeyError:
            timings[ctx.name] = ServiceTiming(0, 0, ctx.calls, ctx.acalls)
    return timings

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

    array = [(name.split(':')[-1], timing.count, timing.total, timing.calls.items(), timing.acalls.items()) \
            for  name, timing in timings.items() if name.startswith('svc:')]
    array.sort(key=lambda x:x[2])

    for name, count, total, calls, acalls in reversed(array):
        print('%-26s     %6d  %f' % (name, count, long(total)/1000.))
        childs = []
        childs += [('tpcall(%s)' % name.split(':')[-1], timing.count, timing.total) for name, timing in calls]
        childs += [('tpacall(%s)' % name.split(':')[-1], timing.count, timing.total) for name, timing in acalls]

        # Sort by timing.total (descending)
        childs.sort(key=lambda x:-x[2])
        for name, count, total in childs:
            print('    %-26s %6d  %f' % (name, count, long(total)/1000.))

def main():
    from optparse import OptionParser
    parser = OptionParser(usage='Usage: %prog [options] <ULOG file>', version='%prog 1.0')
    parser.add_option('-G', '--graph',
            action='store_true', dest='graph',
            help='Produce service call graph')
    parser.add_option('-T', '--timing',
            action='store_true', dest='timing',
            help='Produce service timings')
    parser.add_option('-O', '--output',
            dest='out',
            help='Output file name (.dot or .png for service call graph)')

    (options, args) = parser.parse_args()

    if len(args) != 1:
        parser.error('Please specify input ULOG filename')

    
    if len([fmt for fmt in (options.graph, options.timing) if fmt]) > 1:
        parser.error('Please select only one output type')
    

    if options.graph and not options.out:
        parser.error('Please specify an output filename with "-O file.png" or "--output=file.png"')

    if options.graph:
        do_service_graph(args[0], options.out)
    elif options.timing:
        do_service_timing(args[0])
    else:
        parser.error('No output type selected')

if __name__ == '__main__':
    main()
