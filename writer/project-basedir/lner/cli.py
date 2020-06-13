import time

import datetime
import json
import subprocess

from common.log import logger


class RunCommandException(Exception):
    pass


def h(cmd):
	"""
	Human readable cmd
	"""
	results = []
	results += [cmd[0] + " \\"]
	results += ["  {} \\".format(c) for c in cmd[1:-1]]
	results += ["  {}".format(cmd[-1])]

	return "\n".join(results)

def run(cmd, timeout=5, try_num=3, run_try_sleep=1, log_cmd=True, return_stderr_on_fail=False):
    if log_cmd:
        logger.info("Running command: {}".format(h(cmd)))

    accumulated_timeout = 0
    for _ in range(try_num):
        try_start = time.time()
        kwargs = {}
        if return_stderr_on_fail:
            kwargs["stderr"] = subprocess.STDOUT

        try:
            raw = subprocess.check_output(
                   cmd,
                   timeout=timeout,
                   shell=False,
                   **kwargs
                ).decode("utf-8")
            break
        except Exception as e:
            logger.exception(e)

            raw = e.output
            logger.error("Command output was: {}".format(raw))

            logger.info("Sleeping for {} seconds".format(run_try_sleep))
            time.sleep(run_try_sleep)

        try_duration = time.time() - try_start
        accumulated_timeout += try_duration

        if accumulated_timeout > timeout:
            msg = "Run command {} timeout after {} seconds".format(h(cmd), accumulated_timeout)
            if return_stderr_on_fail:
                return {"success": False, "failure_type": "timeout", "failure_msg": msg, "stdouterr": raw}
            else:
                raise RunCommandException(msg)

    else:
        if return_stderr_on_fail:
            return {
                "success": False,
                "failure_type": "exit",
                "failure_msg": "all retries had non-zero exit status",
                "stdouterr": raw}
        else:
            raise RunCommandException("Failed command: {}".format(h(cmd)))

    if return_stderr_on_fail:
        return {
            "success": True,
            "stdouterr": raw
        }
    else:
        return json.loads(raw)
