"""Environment for external media processes launched from frozen or source builds."""
import os
import sys
from PyQt5.QtCore import QProcessEnvironment


def clean_child_environment():
    environment = QProcessEnvironment.systemEnvironment()
    if getattr(sys, "frozen", False):
        original = os.environ.get("LD_LIBRARY_PATH_ORIG")
        if original:
            environment.insert("LD_LIBRARY_PATH", original)
        else:
            environment.remove("LD_LIBRARY_PATH")
    return environment
