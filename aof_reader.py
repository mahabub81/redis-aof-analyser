import re
import sys
import math
import time
import os
import json
from datetime import datetime

class AofReader:

    current_epoch = None

    start_of_command = True

    total_line_in_a_command = 0

    command_height = 0

    next_line_in_command = 0

    # keys
    keys = {}


    # Key Config
    key_config = {
        'key_separator': ':',
        'key_separated_prefix': [
            'projectname',
            'feature_name'
        ]
    }


    current_key = ''

    current_command = ''

    final_info = {
        'no_of_total_keys_in_redis': {
            'total': 0,
            'by_pattern': {}
        },
        'no_of_expired_keys_in_redis': {
            'total': 0,
            'by_pattern': {}
        },
        'no_of_keys_do_not_have_expiry': {
            'total': 0,
            'by_pattern': {}
        },
        'key_size': {
            'total': 0,
            'by_pattern': {}
        },
        'expiration_time': {},
        'total_commands_run': {
            'total': 0,
            'by_pattern': {}
        }

    }

    def __init__(self, file_path, generate_file_for_expire_keys=None):
        self.file_path = file_path
        self.generate_file_for_expire_keys = generate_file_for_expire_keys;

    def run(self):
        self.final_info['file_size'] = os.path.getsize(self.file_path)
        start_time = time.time()
        self.current_epoch = int(time.time())
        #self.current_epoch = self.current_epoch - 86400
        self.process_file()
        self.generate_final_info(self.generate_file_for_expire_keys)
        self.final_info['execution_time'] = time.time() - start_time
        self.write_output_to_json_file()
        print("==Execution Done===")
        sys.exit()

    def write_output_to_json_file(self):
        json_string = json.dumps(self.final_info)

        # Write the json file
        output_file = open('./final.json', 'w')
        output_file.write(json_string)
        output_file.close()

        # write the js file to generate graph
        output_file = open('./final.js', 'w')
        output_file.write(' var jsonData = `' + json_string +'`;')
        output_file.close()

    def generate_by_pattern_data(self, dictionary_key, pattern, value=1):
        if pattern not in self.final_info[dictionary_key]['by_pattern']:
            self.final_info[dictionary_key]['by_pattern'][pattern] = 0
        self.final_info[dictionary_key]['by_pattern'][pattern] += value

    def calculate_expiration(self, key_details):

        date_time = datetime.fromtimestamp(key_details['expire']).strftime("%Y-%m-%d")

        if date_time not in self.final_info['expiration_time']:
            self.final_info['expiration_time'][date_time] = {}
            self.final_info['expiration_time'][date_time]['by_pattern'] = {}
            self.final_info['expiration_time'][date_time]['total'] = 0

        self.final_info['expiration_time'][date_time]['total'] += 1

        if key_details['pattern'] not in self.final_info['expiration_time'][date_time]['by_pattern']:
            self.final_info['expiration_time'][date_time]['by_pattern'][key_details['pattern']] = 0

        self.final_info['expiration_time'][date_time]['by_pattern'][key_details['pattern']] += 1


    def generate_final_info(self, generate_file_for_expire_keys):
        if generate_file_for_expire_keys is not None:
            file = open(generate_file_for_expire_keys, "w")

        for key in self.keys:
            key_details = self.keys[key]

            ## Populate total size
            self.final_info['key_size']['total'] += key_details['size']
            self.generate_by_pattern_data('key_size', key_details['pattern'], key_details['size'])

            ## Total Keys
            self.final_info['no_of_total_keys_in_redis']['total'] += 1
            self.generate_by_pattern_data('no_of_total_keys_in_redis', key_details['pattern'])

            if key_details['expire'] is 0:
                self.final_info['no_of_keys_do_not_have_expiry']['total'] += 1
                self.generate_by_pattern_data('no_of_keys_do_not_have_expiry', key_details['pattern'])
            else:
                self.calculate_expiration(key_details)
                # keys that have expiry
                if self.current_epoch > key_details['expire']:
                    # already expired but have in redis
                    self.final_info['no_of_expired_keys_in_redis']['total'] += 1
                    self.generate_by_pattern_data('no_of_expired_keys_in_redis', key_details['pattern'], 1)
                    if generate_file_for_expire_keys is not None:
                        file.write("DELETE " + key + "\r\n")

        file.close()

    def process_file(self):
        with open(self.file_path) as infile:
            for line in infile:
                # clean up the line
                line = line.strip()
                is_command_start = self.is_command_start(line)
                if is_command_start is False:
                    self.process_command(line)


    def is_command_start(self, line):
        # we are in the start of a command
        if self.command_height is 0:
            # matches the command starting it must be *[digits], so this command will continue to next (digits * 2) line
            matches = re.match('^\*[0-9]+$', line)
            if matches is None:
                print("Something went wrong")
                sys.exit()
            else:
                self.command_height = int(line.replace("*", "")) * 2
                self.next_line_in_command = 1
            return True
        else:
            return False

    # Process the commands
    def process_command(self, line):
        # it is the command
        if self.next_line_in_command == 2:
            self.add_command_count(line)

        # that is the key
        elif self.next_line_in_command == 4:
            self.process_key(line)
            # FOR delete we have 4 lines only
            if self.current_command == 'DEL' and self.current_key != '':
                self.delete_key()

        else:
            if self.next_line_in_command > 4 and self.next_line_in_command % 2 is 0 and self.current_key != '':
                self.execute_command(line)

        # increment the command line
        self.next_line_in_command += 1
        # decrease the command height
        self.command_height -= 1

    # We did only work with SET and EXPIRE AT Command
    def execute_command(self, command_line):
        command_size_in_bytes = len(command_line.encode('utf-8'))

        if self.current_command == 'SET':
            self.add_key(command_line, command_size_in_bytes)

        if self.current_command == 'PEXPIREAT':
            command_line = math.floor(int(command_line) / 1000)
            self.expire_key(command_line)

    # remove the keys
    def delete_key(self):
        try:
            del self.keys[self.current_key]
            return True
        except:
            return  True

    # Detect key pattern
    def key_pattern(self, key):
        parts = key.split(':')
        if len(parts) <= 2:
            return key
        else:
            for idx, val in enumerate(parts):
                if val.isdigit() is True:
                    del parts[idx]
                    return ':'.join(parts)
        del parts[2]
        return ':'.join(parts)


    # add the key
    def add_key(self, command_line, size):
        if self.current_key not in self.keys:
            self.keys[self.current_key] = {
                'size': size,
                'pattern': self.key_pattern(self.current_key),
                'expire': 0
            }
        else:
            self.keys[self.current_key]['size'] = size

    # key expiry to detect if a key is expired
    def expire_key(self, expiry):
        if self.current_key in self.keys:
            self.keys[self.current_key]['expire'] = expiry

    # Add command count
    def add_command_count(self, line):
        self.current_command = line.upper()
        if self.current_command not in self.final_info['total_commands_run']['by_pattern']:
            self.final_info['total_commands_run']['by_pattern'][self.current_command] = 0
        self.final_info['total_commands_run']['by_pattern'][self.current_command] += 1
        self.final_info['total_commands_run']['total'] += 1

    #process the key
    def process_key(self, line):
        key = self.parse_the_key(line)
        if key is not False:
            self.current_key = key
        else:
            self.current_key = ''

    # parse key
    def parse_the_key(self, line):
        if self.key_config['key_separator'] is None:
            return line
        else:
            key_parts = line.strip().split(self.key_config['key_separator'])
            # key must have two parts
            if (len(key_parts)) < 1 or key_parts[0] not in self.key_config['key_separated_prefix']:
                return False
            else:
                return line


if __name__ == '__main__':
    aof_reader = AofReader('appendonly.aof', './delete.txt')
    aof_reader.run()
