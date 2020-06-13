from common import cli

import time
import json
import random

LNCLI_BIN = "/home/lightning/gocode/bin/lncli"
AUTH_ARGS = [
    "--macaroonpath", "/etc/biostar/writer-{rpcserver}-invoice.macaroon",
    "--tlscertpath", "/etc/biostar/writer-{rpcserver}-tls.cert",
    "--rpcserver", "{rpcserver}"
]


def _sanitize_rpcserver(rpcserver):
    parts = rpcserver.split(":")
    assert len(parts) <= 2, "too many :s in rpcserver"
    assert parts[0].isalnum(), "rpcserver host part in not alphanumeric"
    if len(parts) == 2:
        assert parts[1].isdigit(), "rpcserver port part is not a number"


def _auth_args(rpcserver):
    _sanitize_rpcserver(rpcserver)
    return [arg.format(rpcserver=rpcserver) for arg in AUTH_ARGS]


def addinvoice(memo, rpcserver, amt, expiry):
    """
    TODO (2019-12-20): check for [lncli] rpc error: code = Unknown desc = memo too large: 1192 bytes (maxsize=1024)
         (2020-06-12): saw this issue again while testing
    """
    cmd = [LNCLI_BIN] + _auth_args(rpcserver) + ["addinvoice", "--memo", memo, "--amt", str(amt), "--expiry", str(expiry)]

    # TODO: return_stderr_on_fail=True, and adjust all the call sites
    output = cli.run(cmd)
    print("Command finished, addinvoice json stdout: {}".format(output))
    return output


def listinvoices(index_offset, rpcserver, max_invoices=100, mock=False):
    if mock:
        return {
            "first_index_offset": "0",
                "invoices": [],
                "last_index_offset": "0"
            }

    cmd =  [LNCLI_BIN] + _auth_args(rpcserver) + [
        "listinvoices",
        "--index_offset", str(index_offset),
        "--max_invoices", str(max_invoices),
        "--paginate-forwards",
    ]

    # TODO: return_stderr_on_fail=True, and adjust all the call sites
    return cli.run(cmd, log_cmd=False)

def verifymessage(msg, sig, rpcserver, mock=False):
    """
    NOTE: CLI retruns "pubkey" while API returns "idnetity_pubkey"
    """
    if mock:
        return {
            "valid": True,
            "pubkey": "FAKE2"
        }

    cmd =  [LNCLI_BIN] + _auth_args(rpcserver) + [
        "verifymessage",
        "--msg", msg,
        "--sig", sig,
    ]

    # TODO: return_stderr_on_fail=True, and adjust all the call sites
    return cli.run(cmd, log_cmd=True)

def decodepayreq(payreq, rpcserver, mock=False):
    if mock:
        return {
            "success": True,
            "stdouterr": json.dumps(
                {
                    "num_satoshis": 123,
                    "num_msat": 123000,
                    "pubkey": "FAKE2"
                }
            )
        }

    cmd =  [LNCLI_BIN] + _auth_args(rpcserver) + [
        "decodepayreq",
        "--pay_req", payreq,
    ]

    return cli.run(cmd, log_cmd=True, return_stderr_on_fail=True)

def payinvoice(payreq, rpcserver, mock=False):
    if mock:
        return {"success": True, "stdouterr": ""}

    # TODO: add --json, note that this flag is not defined in older versions of lncli

    cmd =  [LNCLI_BIN] + _auth_args(rpcserver) + [
        "payinvoice",
        "-f",  # force, no interactive prompt
        "--pay_req", payreq,
    ]

    return cli.run(cmd, log_cmd=True, return_stderr_on_fail=True, try_num=3, timeout=60)  # 12x the default timeout!
