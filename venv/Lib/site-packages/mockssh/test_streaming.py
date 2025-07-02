import random
import string


def first_user(server):
    for uid in server.users:
        return uid


def random_string():
    return "".join(random.choice(string.ascii_letters) for _ in range(20))


def streaming_test(server, command, tested_fd, number_of_inputs=1):
    with server.client(first_user(server)) as c:
        fds = stdin, stdout, stderr = c.exec_command(command)
        for i in range(number_of_inputs):
            # the new line is necessary as there is buffering until a new line
            channel_input = random_string() + "\n"
            stdin.write(channel_input)
            channel_output = fds[tested_fd].readline()
            assert channel_output == channel_input


def test_stdin_to_stdout(server):
    return streaming_test(server, "cat", 1)


def test_stdin_to_stderr(server):
    streaming_test(server, "cat 1>&2", 2)


def test_streaming_output(server):
    streaming_test(server, "cat", 1, 100)
