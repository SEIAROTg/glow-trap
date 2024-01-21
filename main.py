#!/usr/bin/env python3

import logging
import os
import ssl
import threading

from aiohttp import web
import dnslib
import dnslib.server
import influxdb_client


DNS_HOST = os.getenv('GLOW_TRAP_DNS_HOST', '0.0.0.0')
DNS_PORT = int(os.getenv('GLOW_TRAP_DNS_PORT', '8053'))

HTTPS_HOST = os.getenv('GLOW_TRAP_HTTPS_HOST', '0.0.0.0')
HTTPS_PORT = int(os.getenv('GLOW_TRAP_HTTPS_PORT', '8443'))
HTTPS_PUBLIC_HOST = os.getenv('GLOW_TRAP_HTTPS_PUBLIC_HOST', '')
assert HTTPS_PUBLIC_HOST, 'GLOW_TRAP_HTTPS_PUBLIC_HOST must be set'

INFLUXDB_BUCKET = os.getenv('GLOW_TRAP_INFLUXDB_BUCKET', 'glow-trap')

KEY_PATH = os.path.join(os.path.dirname(__file__), 'key.pem')
CERT_PATH = os.path.join(os.path.dirname(__file__), 'cert.pem')

LOG_PATH = os.getenv('GLOW_TRAP_LOG_PATH', '')


def get_logger():
    logger = logging.getLogger('glow-trap')
    formatter = logging.Formatter('%(asctime)-15s [%(levelname)s]  %(message)s')
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)
    if LOG_PATH:
        file_handler = logging.FileHandler(LOG_PATH)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    logger.setLevel(logging.INFO)
    return logger


logger = get_logger()


def decode_hex(hex: str, signed: bool = False) -> int:
    ret = int(hex, 16)
    m = 1 << (len(hex) * 4)
    if signed and ret >= m / 2:
        ret -= m
    return ret


class NameResolver(dnslib.server.BaseResolver):
    def resolve(self, request, handler):
        qname = request.q.qname
        reply = request.reply()

        if qname.matchSuffix('cad.sensornet.info') or qname.matchSuffix('pool.ntp.org'):
            reply.add_answer(dnslib.RR(
                rname=qname,
                rtype=dnslib.QTYPE.A,
                rclass=dnslib.CLASS.IN,
                ttl=600,
                rdata=dnslib.A(HTTPS_PUBLIC_HOST),
            ))
        else:
            reply.header.rcode = dnslib.RCODE.NXDOMAIN
        return reply


class DNSServer(dnslib.server.DNSServer):
    def __init__(self):
        resolver = NameResolver()
        super().__init__(
            resolver,
            port=DNS_PORT,
            address=DNS_HOST,
            logger=dnslib.server.DNSLogger(log='error'))


class HTTPSServer:
    def start(self):
        influx_client = influxdb_client.InfluxDBClient.from_env_properties()
        self._influx_write_api = influx_client.write_api()

        logging.getLogger('aiohttp').setLevel(logging.CRITICAL + 1)
        ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ssl_context.load_cert_chain(CERT_PATH, KEY_PATH)
        app = web.Application()
        app.add_routes([
            web.post('/zb02', self._handle_request),
        ])
        web.run_app(app, host=HTTPS_HOST, port=HTTPS_PORT, print=None, ssl_context=ssl_context)

    async def _handle_request(self, req):
        body = await req.text()
        try:
            if body.startswith('EPRICE:'):
                return await self._handle_price(req)
            return await self._handle_reading(req)
        except Exception:
            logger.exception(
                f'Error processing request:\nheaders={req.headers!r}\nbody={body}')
        return web.Response(text='200')

    async def _handle_price(self, req):
        body = await req.text()
        lines = body.split('\r\n')
        eprice_line = lines[0].split('EPRICE:', 1)[1]
        eprice_segs = eprice_line.split(',')
        price_label = eprice_segs[3]
        unit_price = decode_hex(eprice_segs[12])

        estdchg_line = lines[1].split('ESTDCHG:', 1)[1]
        estdchg_segs = estdchg_line.split(',')
        standing_charge = decode_hex(estdchg_segs[0])

        self._influx_write_api.write(INFLUXDB_BUCKET, record=[{
            'measurement': 'price',
            'tags': {
                'device_id': req.headers['X-ID'],
            },
            'time': decode_hex(req.headers['X-TS']) * 10 ** 9,
            'fields': {
                'unit_price': unit_price,
                'standing_charge': standing_charge,
            },
        }])

    async def _handle_reading(self, req):
        data = await req.json()
        point = {
            'measurement': 'reading',
            'tags': {
                'device_id': req.headers['X-ID'],
            },
            'time': decode_hex(data['time']) * 10 ** 9,
            'fields': {
                'status': data['pan']['status'],
                'lqi': decode_hex(data['pan']['lqi']),
                'rssi': decode_hex(data['pan']['rssi'], signed=True),
                'header_time': decode_hex(req.headers['X-TS']),
            },
        }
        meter = data.get('elecMtr', {}).get('0702')
        if meter:
            point['fields']['reading'] = decode_hex(meter['00']['00'])
            point['fields']['instant'] = decode_hex(meter['04']['00'], signed=True)
        self._influx_write_api.write(INFLUXDB_BUCKET, record=point)


if __name__ == '__main__':
    threading.Thread(target=DNSServer().start).start()
    HTTPSServer().start()
