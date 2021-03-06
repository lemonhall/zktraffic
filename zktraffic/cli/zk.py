# -*- coding: utf-8 -*-

# ==================================================================================================
# Copyright 2015 Twitter, Inc.
# --------------------------------------------------------------------------------------------------
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this work except in compliance with the License.
# You may obtain a copy of the License in the LICENSE file, or at:
#
#  http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==================================================================================================

from collections import defaultdict, deque
from datetime import datetime
import sys
import threading
import time
import zlib

from zktraffic.base.sniffer import Sniffer, SnifferConfig

import colors
from twitter.common import app


def setup():
  app.add_option('--iface', default='eth0', type=str)
  app.add_option('--client-port', default=0, type=int)
  app.add_option('--zookeeper-port', default=2181, type=int)
  app.add_option('--max-queued-requests', default=10000, type=int)
  app.add_option('-p', '--include-pings', default=False, action='store_true')
  app.add_option('-c', '--colors', default=False, action='store_true')


class Requests(object):
  def __init__(self):
    self.requests_by_xid = defaultdict(list)

  def add(self, req):
    self.requests_by_xid[req.xid].append(req)

  def pop(self, xid):
    return self.requests_by_xid.pop(xid) if xid in self.requests_by_xid else []


right_arrow = lambda i: "%s%s" % ("—" * i * 4, "►" if i > 0 else "")


def format_timestamp(timestamp):
  dt = datetime.fromtimestamp(timestamp)
  return dt.strftime("%H:%M:%S:%f")


class MessagePrinter(threading.Thread):
  NUM_COLORS = len(colors.COLORS)

  def __init__(self, colors, loopback):
    super(MessagePrinter, self).__init__()
    self.default_handler = self.colored_handler if colors else self.simple_handler
    self._requests_by_client = defaultdict(Requests)
    self._replies = deque()
    self._loopback = loopback

    self.setDaemon(True)

  def run(self):
    while True:
      try:
        rep = self._replies.popleft()
      except IndexError:
        time.sleep(0.1)
        continue

      reqs = self._requests_by_client[rep.client].pop(rep.xid)
      if not reqs:
        continue

      # HACK: if we are on the loopback, drop dupes
      msgs = reqs[0:1] + [rep] if self._loopback else reqs + [rep]
      self.default_handler(*msgs)

  def request_handler(self, req):
    self._requests_by_client[req.client].add(req)

  def reply_handler(self, rep):
    self._replies.append(rep)

  def colored_handler(self, *msgs):
    c = colors.COLORS[zlib.adler32(msgs[0].client) % self.NUM_COLORS]
    cfunc = getattr(colors, c)
    for i, m in enumerate(msgs):
      sys.stdout.write(cfunc("%s%s %s" % (right_arrow(i), format_timestamp(m.timestamp), m)))
    sys.stdout.flush()

  def simple_handler(self, *msgs):
    for i, m in enumerate(msgs):
      sys.stdout.write("%s%s %s" % (right_arrow(i), format_timestamp(m.timestamp), m))
    sys.stdout.flush()


def main(_, options):
  config = SnifferConfig(options.iface)
  config.track_replies = True
  config.zookeeper_port = options.zookeeper_port
  config.max_queued_requests = options.max_queued_requests
  config.client_port = options.client_port if options.client_port != 0 else config.client_port

  config.update_filter()

  if options.include_pings:
    config.include_pings()

  loopback = options.iface in ["lo", "lo0"]
  mp = MessagePrinter(options.colors, loopback=loopback)
  mp.start()

  sniffer = Sniffer(config, mp.request_handler, mp.reply_handler, mp.default_handler)
  sniffer.start()

  try:
    while True:
      time.sleep(60)
  except (KeyboardInterrupt, SystemExit):
    pass

  sys.stdout.write("\033[0m")
  sys.stdout.flush()


if __name__ == '__main__':
  setup()
  app.main()
