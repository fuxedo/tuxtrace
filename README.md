# tuxtrace
DIY Oracle Tuxedo monitoring

## ulog-trace.py

This script parses ULOG file and produces outputs in different formats.

But first you have to tell Oracle Tuxedo to put enough details into ULOG. By default timestamps have seconds precision and you will have to add new environment variable and restart the whole application to have milliseconds precision:

```
ULOGMILLISEC=Y; export ULOGMILLISEC
```

You must also tell Oracle Tuxedo to trace all ATMI calls but be aware that it has a performance penalty. Commands for turning it on or off are:

```
# on
echo 'chtr "*:ulog:dye"' | tmadmin
# off
echo 'chtr off' | tmadmin
```

If you have Tuxedo client applications that call server applications you should also export the environment variable:

```
TMTRACE=on; export TMTRACE
```

If everything worked fine and your application is working you should see entries like this in the ULOG:

```
013532.928.burzum!HUB.7442.3948934912.1: TRACE:at:  { tpalloc("FML32", "-", 1024)
013532.928.burzum!HUB.7442.3948934912.1: TRACE:at:  } tpalloc = 0x0x1a4e2f8
013532.930.burzum!HUB.7441.508056256.0: gtrid x0 x5804a5c5 x21ff: TRACE:at:    { tpcall("OUT", 0x0x10df518, 0, 0x0x7ffe20890ba0, 0x0x7ffe20890a20, 0x0)
```

Now you are ready to analyze your application!

### Profiler

```
python ulog-trace.py -T log/ULOG.040516
```

For the same demo application gives:

```
HUB                                40  3.458000
    tpcall(OUT)                    40  1.746000
    tpacall(SVCB)                  40  0.008000
    tpacall(SVCA)                  40  0.006000
IN                                 40  2.769000
    tpacall(HUB)                   40  0.007000
OUT                                40  1.734000
SVCA                               40  1.710000
SVCB                               40  1.682000
```

It shows service name, number of times service was called and cummulative time
spent in service. For each service it shows also tpcall()s and tpacall()s made,
number of times it was performed and cummulative time spent. One thing to
notice is that service OUT executed for 1.734 seconds but caller spent 1.746
seconds calling it. It's due to time request and response messages spend in IPC
queues and the difference is even bigger for systems under load.

The first number is number of times service is called


### Callgraph

This output requries you to have Graphviz installed on you computer and it uses
dot to create the graph.

```
python ulog-trace.py -G log/ULOG.040516 -O callgraph.png
```

Gives output like this one (for my simplified demo application):

![](http://aivarsk.github.io/public/callgraph.png)

Line represents a tpcall() and a dashed line represents a tpacall()

### Monitoring

For monitoring the script will continue reading ULOG while application writes
to it and periodically report it to monitoring software. This can cause a
performance penalty because the logfile has to be written and a process is
reading and parsing it at the same time.

I have a C module that has low performance impact because it writes interesting
entries to shared memory region but that's a different story.

#### Graphite

```
python ulog-trace.py --graphite 127.0.0.1:2003
```

For each service it reports following metrics:

Tuxedo.$SERVICE.calls
Tuxedo.$SERVICE.errors
Tuxedo.$SERVICE.tottime
Tuxedo.$SERVICE.cumtime


#### AppDynamics

For AppDynamics script will poll ULOG and send new metrics every minute to machine agent over HTTP.

```
python ulog-trace.py --appdynamics http://127.0.0.1:7890/api/v1/metrics
```

For each service it reports following metrics:

Custom Metrics|Tuxedo|Services|$SERVICE|Number of Calls
Custom Metrics|Tuxedo|Services|$SERVICE|Failures
Custom Metrics|Tuxedo|Services|$SERVICE|Total Time (msec)
Custom Metrics|Tuxedo|Services|$SERVICE|Cumulative Time (msec)


You will also need [machine-agent with HTTP listener enabled](https://docs.appdynamics.com/display/PRO42/Standalone+Machine+Agent+HTTP+Listener)
