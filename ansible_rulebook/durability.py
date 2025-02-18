#  Copyright 2022 Red Hat, Inc.
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.

import datetime
import logging

import redis

logger = logging.getLogger(__name__)


def unix_time(dt):
    epoch = datetime.datetime.utcfromtimestamp(0)
    delta = dt - epoch
    return int(delta.total_seconds() * 1000.0)


def provide_durability(host, redis_host_name="localhost", port=6379):
    r = redis.StrictRedis(
        redis_host_name, port, charset="utf-8", decode_responses=True
    )

    def get_hset_name(ruleset, sid):
        return "h!{0}!{1}".format(ruleset, sid)

    def get_list_name(ruleset, sid):
        return "l!{0}!{1}".format(ruleset, sid)

    def get_sset_name(ruleset):
        return "s!{0}".format(ruleset)

    def format_message(action_type, content):
        return "{0},{1}".format(action_type, content)

    def format_messages(results):
        if not results:
            return "[]"

        messages = ["["]
        for i in range(0, len(results)):
            messages.append(results[i])
            if i < (len(results) - 1):
                messages.append(",")

        messages.append("]")
        return "".join(messages)

    def store_message_callback(ruleset, sid, mid, action_type, content):
        try:
            r.hset(
                get_hset_name(ruleset, sid),
                mid,
                format_message(action_type, content),
            )
        except BaseException:
            logger.exception("BaseException encountered")
            return 601

        return 0

    def delete_message_callback(ruleset, sid, mid):
        try:
            r.hdel(get_hset_name(ruleset, sid), mid)
        except BaseException:
            logger.exception("BaseException encountered")
            return 602

        return 0

    def queue_message_callback(ruleset, sid, action_type, content):
        try:
            result = r.zscore(get_sset_name(ruleset), sid)
            if not result:
                r.zadd(
                    get_sset_name(ruleset),
                    {sid: unix_time(datetime.datetime.now())},
                )

            r.rpush(
                get_list_name(ruleset, sid),
                format_message(action_type, content),
            )
        except BaseException:
            logger.exception("BaseException encountered")
            return 603

        return 0

    def get_queued_messages_callback(ruleset, sid):
        try:
            r.zadd(
                get_sset_name(ruleset),
                {sid: unix_time(datetime.datetime.now()) + 5000},
            )
            messages = r.lrange(get_list_name(ruleset, sid), 0, -1)
            if len(messages):
                r.delete(get_list_name(ruleset, sid))
                host.complete_get_queued_messages(
                    ruleset, sid, format_messages(messages)
                )
        except BaseException:
            logger.exception("BaseException encountered")
            return 604

        return 0

    def get_idle_state_callback(ruleset):
        try:
            results = r.zrangebyscore(
                get_sset_name(ruleset), 0, unix_time(datetime.datetime.now())
            )
            if results and len(results):
                sid = results[0]
                messages = r.hvals(get_hset_name(ruleset, sid))
                host.complete_get_idle_state(
                    ruleset, sid, format_messages(messages)
                )
        except BaseException:
            logger.exception("BaseException encountered")
            return 606

        return 0

    host.set_store_message_callback(store_message_callback)
    host.set_delete_message_callback(delete_message_callback)
    host.set_queue_message_callback(queue_message_callback)
    host.set_get_idle_state_callback(get_idle_state_callback)
    host.set_get_queued_messages_callback(get_queued_messages_callback)
