# Copyright (c) 2023 Daniel Vince.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

from .events import EventHandler

class EventListener:
    def __init__(self):
        self._handlers = []

    def subscribe(self, handler: EventHandler) -> None:
        self._handlers.append(handler)

    def unsubscribe(self, handler: EventHandler) -> None:
        self._handlers.remove(handler)

    def notify(self, event, data) -> None:
        for handler in self._handlers:
            try:
                func = getattr(handler, event)
                func(**data)
            except AttributeError as e:
                print(e)
