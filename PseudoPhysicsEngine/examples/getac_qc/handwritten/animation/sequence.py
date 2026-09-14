from cellforge.build.seq import actuate, capture, emit, move_joint, wait_for


def build():
    actuate("infeed_rack.lift", 160, duration_s=7, station="S1", unit="mm")
    wait_for(2, station="S1")
    emit("S1.done")

    capture("vision_fixture", station="S2", duration_s=3)
    wait_for(4, station="S2")
    emit("S2.done")

    move_joint("robot_1", [20, -30, 45, 0, 35, 10], duration_s=7, station="S3")
    actuate("workpiece.cover_lan", 110, duration_s=3, station="S3", unit="deg")
    move_joint("robot_1", [5, -15, 25, 0, 20, 0], duration_s=4, station="S3")
    emit("S3.done")

    move_joint("robot_2", [-15, -25, 55, 90, 20, 0], duration_s=8, station="S4")
    move_joint("robot_2", [10, -10, 35, 180, 15, 0], duration_s=6, station="S4")
    capture("robot_2.camera", station="S4", duration_s=2)
    emit("S4.done")

    actuate("outfeed_rack.lift", 240, duration_s=7, station="S5", unit="mm")
    wait_for(2, station="S5")
    emit("S5.done")
