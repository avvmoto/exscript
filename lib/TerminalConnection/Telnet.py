from Transport import Transport as Base
import re, exceptions, sys, otp
import telnetlib

True  = 1
False = 0

cisco_user_re = re.compile(r'[\r\n]username: ', re.I)
junos_user_re = re.compile(r'[\r\n]login: ?',   re.I)
unix_user_re  = re.compile(r'(user|login): ?',  re.I)
pass_re       = re.compile(r'password:? ?',     re.I)
skey_re       = re.compile(r'(?:s\/key|otp-md4) (\d+) (\S+)')
prompt_re     = re.compile(r'[\r\n][\-\w\(\)@]+[#>%] ?', re.I)

class Transport(Base):
    def __init__(self, *args, **kwargs):
        Base.__init__(self, **kwargs)
        self.tn        = None
        self.timeout   = 30
        self.host_type = 'unknown'
        self.debug     = kwargs.get('debug',   0)
        self.echo      = kwargs.get('echo',    False)
        self.logfile   = kwargs.get('logfile', None)
        self.log       = None
        self.prompt    = prompt_re
        if self.logfile is not None:
            self.log = open(kwargs['logfile'], 'a')


    def __del__(self):
        if self.log is not None:
            self.log.close()


    def _receive_cb(sender, data, *args, **kwargs):
        self = kwargs['telnet']
        data = data.replace('\r', '')
        if self.echo:
            sys.stdout.write(data)
            sys.stdout.flush()
        if self.log is not None:
            self.log.write(data)
        if self.on_data_received_cb is not None:
            self.on_data_received_cb(data, self.on_data_received_args)
        return data


    def set_prompt(self, prompt = None):
        if prompt is None:
            self.prompt = prompt_re
        else:
            self.prompt = prompt


    def set_timeout(self, timeout):
        self.timeout = timeout


    def connect(self, hostname):
        assert self.tn is None
        self.tn = telnetlib.Telnet(hostname)
        self.tn.set_receive_callback(self._receive_cb, telnet = self)
        #self.tn.set_debuglevel(1)
        if self.tn is None:
            return False
        return True


    def authenticate(self, user, password):
        # Wait for the user prompt.
        #print 'Waiting for prompt'
        host_type   = ['cisco',       'junos',       'unix']
        user_prompt = [cisco_user_re, junos_user_re, unix_user_re]
        which       = None
        if self.debug > 0:
            (which, _, _)  = self.tn.expect(user_prompt, self.timeout)
            self.host_type = host_type[which]
        else:
            try:
                (which, _, _)  = self.tn.expect(user_prompt, self.timeout)
                self.host_type = host_type[which]
            except:
                raise Exception("Error while waiting for username prompt")

        # Send the user name.
        self.send(user + '\n')

        # Wait for the password, s/key, or the shell prompt.
        prompt  = [skey_re, pass_re, self.prompt]
        which   = None
        matches = None
        if self.debug > 0:
            (which, matches, _) = self.tn.expect(prompt, self.timeout)
        else:
            try:
                (which, matches, _) = self.tn.expect(prompt, self.timeout)
            except:
                raise Exception("Error while waiting for password prompt")

        # Send the password (if a password prompt was received).
        if which == 0:
            seq    = int(matches.group(1))
            seed   = matches.group(2)
            #print "Seq:", seq, "Seed:", seed
            phrase = otp.generate(password, seed, seq, 1, 'md4', 'sixword')[0]
            self.send(phrase + '\n')
            self.expect_prompt()
        elif which == 1:
            self.send(password + '\n')
            self.expect_prompt()

        #FIXME: Fetch login errors.

        # Switch to script compatible output (where supported).
        #print 'Host type:', self.host_type
        if self.host_type == 'cisco':
            self.execute('terminal length 0')


    def authorize(self, password):
        # Make sure that the device supports AAA.
        if self.host_type != 'cisco':
            return

        self.send('en\n')

        # Wait for the password, s/key, or the shell prompt.
        prompt = [skey_re, pass_re, self.prompt]
        try:
            (which, matches, _) = self.tn.expect(prompt, self.timeout)
        except:
            raise Exception("Error while waiting for password prompt")

        # Send the password (if a password prompt was received).
        if which == 0:
            seq    = int(matches.group(1))
            seed   = matches.group(2)
            #print "Seq:", seq, "Seed:", seed
            phrase = otp.generate(password, seed, seq, 1, 'md4', 'sixword')[0]
            self.send(phrase + '\n')
        elif which == 1:
            self.send(password + '\n')
        elif which == 2:
            return

        # Wait for a prompt.
        self.expect_prompt()


    def expect_prompt(self):
        # Wait for a prompt.
        try:
            (_, _, response) = self.tn.expect([self.prompt], self.timeout)
        except:
            raise Exception("Error while waiting for the prompt")
        if response is None:
            return response
        return response.split('\n')
        

    def send(self, data):
        #print 'Sending "%s"' % data
        try:
            self.tn.write(data)
        except:
            raise Exception("Error while writing to connection")


    def execute(self, data):
        # Send the command.
        self.send(data + '\n')
        return self.expect_prompt()


    def close(self):
        self.tn.close()
