from cellforge.build.seq import emit, wait_for


def build():
    wait_for(1.0, station="S1")
    emit("S1.done")
