import zmq

def main():
    # 建立 Context
    context = zmq.Context()

    # 建立 REP Socket (Server)
    socket = context.socket(zmq.REP)

    # 綁定 Port
    socket.bind("tcp://*:5555")

    print("ZeroMQ Server 啟動，等待連線...")

    while True:
        try:
            # 接收訊息
            message = socket.recv_string()

            print(f"收到訊息: {message}")

            # 回覆 Client
            socket.send_string("OK")

        except KeyboardInterrupt:
            print("Server停止")
            break

    socket.close()
    context.term()

if __name__ == "__main__":
    main()