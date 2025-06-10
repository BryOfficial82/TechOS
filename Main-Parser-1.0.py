import re
import ast
import sys
import readline

# Attempt to import network libraries. These are not built-in, so a check is necessary.
try:
    import requests
except ImportError:
    requests = None # Mark as unavailable
    print("WARNING: 'requests' library not found. Network commands (FCH/FETCH) will not work.")

try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None # Mark as unavailable
    print("WARNING: 'BeautifulSoup4' library (bs4) not found. HTML prettification will not work.")

# NEW: Attempt to import html2text library
try:
    import html2text
except ImportError:
    html2text = None
    print("WARNING: 'html2text' library not found. Text decoding will not work.")


class SPiDInterpreter:
    def __init__(self, script_lines=None):
        self.variables = {}
        self.ram = {}
        self.commands = self.parse_SPiD_definition()
        
        self.handlers = {
            "CMP": self.handle_cmp,
            "LOGIC_AND": self.handle_logic_and,
            "LOGIC_OR": self.handle_logic_or,
            "LOGIC_NOR": self.handle_logic_nor,
            "LOGIC_XNOR": self.handle_logic_xnor,
            "LOGIC_XOR": self.handle_logic_xor,
            "ARITH_ADD": self.handle_arith_add,
            "ARITH_SUB": self.handle_arith_sub,
            "ARITH_MULT": self.handle_arith_mult,
            "ARITH_DIV": self.handle_arith_div,
            "PRINT_CMD": self.handle_print,
            "BOOL_SET": self.handle_bool_set,
            "PYTHON_CMD": self.handle_python,
            "JUMP_CMD": self.handle_jump,
            "INPUT_CMD": self.handle_input,
            "CD_CMD": self.handle_cd,  # Added CD handler
            "LS_CMD": self.handle_ls,  # Added LS handler
            "NETWORK_FETCH": self.handle_network_fetch, # New network command handler
        }
        self.script_lines = script_lines
        self.program_counter = 0

    def parse_SPiD_definition(self):
        SPiD_definition = """
        main.spid<
        TYPE=SPiD

        # ARITHMETIC
        ADD (VAR,VAL) (VAR,VAL) (VAR) [CMD=ARITH_ADD]
        SUB (VAR,VAL) (VAR,VAL) (VAR) [CMD=ARITH_SUB]
        MULT (VAR,VAL) (VAR,VAL) (VAR) [CMD=ARITH_MULT]
        DIVS (VAR,VAL) (VAR,VAL) (VAR) [CMD=ARITH_DIV]

        # LOGIC
        IF (VAR,VAL) (VAR,VAL) (HIGH,LOW,EQUAL) (THEN,ELSE) (SCRIPT) [CMD=CMP]
        BOOL (BIN) (VAR) [CMD=BOOL_SET]
        AND (VAR) (VAR) (VAR) [CMD=LOGIC_AND]
        OR (VAR) (VAR) (VAR) [CMD=LOGIC_OR]
        NOR (VAR) (VAR) (VAR) [CMD=LOGIC_NOR]
        XNOR (VAR) (VAR) (VAR) [CMD=LOGIC_XNOR]
        XOR (VAR) (VAR) (VAR) [CMD=LOGIC_XOR]

        # PRINT
        PRINT (1,0) (VAR,TXT) [CMD=PRINT_CMD]

        # INPUT
        INPUT (VAR) [CMD=INPUT_CMD]

        # PYTHON
        PYTHON (TXT) [CMD=PYTHON_CMD]

        # CONTROL FLOW
        JUMP (VAR,VAL) [CMD=JUMP_CMD]

        # FILE SYSTEM
        ET (TXT) [CMD=CD_CMD]
        LI (BIN) (TXT) [CMD=LS_CMD]

        # NETWORK (New commands)
        # UPDATED: Added (VAR,TXT) for language_val as the 5th argument
        #           The last two arguments shifted position.
        # FCH (url) (raw_response_var) (client_agent) (format_val) (language_val) (decode_type) (decoded_output_var)
        FCH (VAR,TXT) (VAR) (VAR,TXT) (VAR,TXT) (VAR,TXT) (TXT) (VAR) [CMD=NETWORK_FETCH]
        FETCH (VAR,TXT) (VAR) (VAR,TXT) (VAR,TXT) (VAR,TXT) (TXT) (VAR) [CMD=NETWORK_FETCH] # Alias for FCH

        END
        """

        commands = {}
        in_commands = False
        for line in SPiD_definition.split('\n'):
            line = line.strip()
            if line.startswith('main.spid<'):
                in_commands = True
                continue
            if line.startswith('END'):
                break
            if not in_commands or not line:
                continue
            
            if '#' in line:
                line = line.split('#', 1)[0].strip()
                if not line:
                    continue

            match = re.match(r'^(\w+)\s+(.+?)(?:\s*\[CMD=(\w+)\])?$', line)
            if match:
                cmd = match.group(1).upper()
                pattern = match.group(2).strip()
                handler = match.group(3) if match.group(3) else None
                commands[cmd] = {
                    'pattern': pattern,
                    'handler': handler,
                    'arg_count': len(re.findall(r'\(([^)]+)\)', pattern))
                }
        return commands

    def parse_value(self, token):
        if token.startswith('"') and token.endswith('"'):
            return token[1:-1]
        try:
            return float(token)
        except ValueError:
            pass
        if token == '0':
            return 0.0
        if token == '1':
            return 1.0
        if token.upper() == 'NULL': # Treat 'NULL' as a special keyword
            return "NULL"
        if token in self.variables:
            return self.variables[token]
        return token

    def tokenize(self, line):
        tokens = []
        current = ""
        in_quotes = False
        escape = False

        for char in line:
            if escape:
                current += char
                escape = False
            elif char == '\\':
                escape = True
            elif char == '"':
                in_quotes = not in_quotes
                current += char
            elif char == ' ' and not in_quotes:
                if current:
                    tokens.append(current)
                    current = ""
            else:
                current += char

        if current:
            tokens.append(current)
        return tokens

    def execute_line(self, line):
        line = line.strip()
        if not line:
            return

        # Corrected variable declaration parsing
        if line.startswith('<') and line.endswith('>'):
            # Remove any comments before processing the declaration
            clean_line = line.split('#', 1)[0].strip()
            if not clean_line.endswith('>'): # Ensure the > is still there after comment removal
                print(f"Invalid variable declaration format: {line} (missing closing '>')")
                return

            decl = clean_line[1:-1].split('=', 1)
            if len(decl) == 2:
                var, val = decl
                parsed_val = self.parse_value(val.strip())
                self.variables[var.strip()] = parsed_val
                return
            else:
                print(f"Invalid variable declaration: {line}")
                return

        tokens = self.tokenize(line)
        if not tokens:
            return

        cmd = tokens[0].upper()
        raw_args = tokens[1:]

        if cmd not in self.commands:
            print(f"Unknown command: {cmd}")
            return

        command_def = self.commands[cmd]
        handler_name = command_def['handler']
        arg_count = command_def['arg_count']

        if not handler_name or handler_name not in self.handlers:
            print(f"No handler for command: {cmd}")
            return

        parsed_args = []
        if cmd == "PRINT":
            parsed_args.append(self.parse_value(raw_args[0]))
            if len(raw_args) > 1:
                content_to_parse = ' '.join(raw_args[1:])
                if int(self.parse_value(raw_args[0])) == 0:
                     parsed_args.append(raw_args[1]) # Pass variable NAME for flag 0
                else:
                    parsed_args.append(content_to_parse) # Pass raw text for flag 1
            else:
                print(f"Warning: PRINT command with flag {raw_args[0]} has no content.")
                parsed_args.append("")
        elif cmd == "IF":
            for i in range(arg_count - 1):
                parsed_args.append(self.parse_value(raw_args[i]))
            parsed_args.append(' '.join(raw_args[arg_count-1:]))
        elif cmd == "PYTHON":
            parsed_args.append(' '.join(raw_args))
        elif cmd == "INPUT":
            parsed_args.append(raw_args[0]) # Pass raw variable name for input
        elif cmd == "ET": # Handling for ET (CD)
            parsed_args.append(' '.join(raw_args))
        elif cmd == "LI": # Handling for LI (LS)
            parsed_args.append(self.parse_value(raw_args[0]))
            if len(raw_args) > 1:
                parsed_args.append(' '.join(raw_args[1:]))
            else:
                parsed_args.append('')
        elif cmd == "FCH" or cmd == "FETCH": # Network Command: SPECIAL HANDLING FOR VAR NAMES and NEW DECODE TYPE
             # Arg 0: URL (VAR,TXT) -> value
             parsed_args.append(self.parse_value(raw_args[0]))
             # Arg 1: RAW_RESPONSE_VAR (VAR) -> name (pass raw token)
             parsed_args.append(raw_args[1])
             # Arg 2: CLIENT_AGENT_VALUE (VAR,TXT) -> value
             parsed_args.append(self.parse_value(raw_args[2]))
             # Arg 3: FORMAT_TYPE (VAR,TXT) -> value
             parsed_args.append(self.parse_value(raw_args[3]))
             # NEW ARGUMENT: Arg 4: LANGUAGE_VAL (VAR,TXT) -> value
             parsed_args.append(self.parse_value(raw_args[4]))
             # Arg 5 (shifted): DECODE_TYPE (TXT) -> value (e.g., "HTML", "TEXT", "RAW", "NONE")
             parsed_args.append(self.parse_value(raw_args[5]))
             # Arg 6 (shifted): DECODED_OUTPUT_VAR (VAR) -> name (pass raw token)
             parsed_args.append(raw_args[6])
             
             # Pad with NULLs if arguments are missing, though arg_count check should handle this
             while len(parsed_args) < arg_count:
                 parsed_args.append("NULL") 

        else: # Generic parsing for commands not explicitly handled above
            for token in raw_args:
                parsed_args.append(self.parse_value(token))

        try:
            # Ensure the number of arguments matches expected, or it's a TypeError
            if len(parsed_args) != arg_count:
                 print(f"Argument error in {cmd}: Expected {arg_count} arguments, but got {len(parsed_args)}.")
                 return
            self.handlers[handler_name](*parsed_args) # Pass all parsed args
        except TypeError as e:
            print(f"Argument error in {cmd}: {str(e)}. Check command definition and arguments.")
        except Exception as e:
            print(f"Error executing {cmd}: {str(e)}")

    def handle_cmp(self, val1, val2, condition, branch, script):
        try:
            val1 = float(val1)
            val2 = float(val2)
        except (ValueError, TypeError):
            print("IF command requires numeric values")
            return

        condition = condition.upper()
        branch = branch.upper()

        condition_met = False
        if condition == 'HIGH' and val1 > val2:
            condition_met = True
        elif condition == 'LOW' and val1 < val2:
            condition_met = True
        elif condition == 'EQUAL' and val1 == val2:
            condition_met = True
        else:
            print(f"Invalid condition: {condition}")
            return

        if (branch == 'THEN' and condition_met) or (branch == 'ELSE' and not condition_met):
            self.execute_line(script)

    def handle_logic_gate(self, in1, in2, out, gate_type):
        try:
            val1 = bool(float(in1))
            val2 = bool(float(in2))
        except (ValueError, TypeError):
            print("Logic gates require numeric values (0 or 1)")
            return

        if gate_type == "AND":
            result = val1 and val2
        elif gate_type == "OR":
            result = val1 or val2
        elif gate_type == "NOR":
            result = not (val1 or val2)
        elif gate_type == "XNOR":
            result = val1 == val2
        elif gate_type == "XOR":
            result = val1 != val2
        else:
            print(f"Unknown gate type: {gate_type}")
            return

        self.variables[out] = float(int(result))

    def handle_logic_and(self, in1, in2, out):
        self.handle_logic_gate(in1, in2, out, "AND")

    def handle_logic_or(self, in1, in2, out):
        self.handle_logic_gate(in1, in2, out, "OR")

    def handle_logic_nor(self, in1, in2, out):
        self.handle_logic_gate(in1, in2, out, "NOR")

    def handle_logic_xnor(self, in1, in2, out):
        self.handle_logic_gate(in1, in2, out, "XNOR")

    def handle_logic_xor(self, in1, in2, out):
        self.handle_logic_gate(in1, in2, out, "XOR")

    def handle_arith(self, a, b, out, op):
        try:
            a_val = float(a)
            b_val = float(b)
        except (ValueError, TypeError):
            print("Arithmetic operations require numeric values")
            return

        if op == "ADD":
            result = a_val + b_val
        elif op == "SUB":
            result = a_val - b_val
        elif op == "MULT":
            result = a_val * b_val
        elif op == "DIV":
            if b_val == 0.0:
                print("Division by zero")
                return
            result = a_val / b_val
        else:
            print(f"Unknown operation: {op}")
            return

        self.variables[out] = result

    def handle_arith_add(self, a, b, out):
        self.handle_arith(a, b, out, "ADD")

    def handle_arith_sub(self, a, b, out):
        self.handle_arith(a, b, out, "SUB")

    def handle_arith_mult(self, a, b, out):
        self.handle_arith(a, b, out, "MULT")

    def handle_arith_div(self, a, b, out):
        self.handle_arith(a, b, out, "DIV")

    def handle_print(self, flag, content_raw):
        """Handle print command"""
        try:
            flag_int = int(flag)

            if flag_int == 0:
                # content_raw is now guaranteed to be the variable NAME if flag is 0
                if content_raw in self.variables:
                    print(self.variables[content_raw])
                else:
                    print(f"Undefined variable: {content_raw}") # It's a variable name, but not in variables dict

            elif flag_int == 1:
                # content_raw is already parsed value (string literal) for flag 1
                if isinstance(content_raw, str) and content_raw.startswith('"') and content_raw.endswith('"'):
                    content_raw = content_raw[1:-1] # Remove quotes if parse_value didn't
                print(content_raw)
            else:
                print(f"Invalid PRINT flag: {flag}. Use 0 for variables or 1 for text.")
        except Exception as e:
            print(f"Print error: {str(e)}")


    def handle_bool_set(self, value, var):
        try:
            val = float(value)
            if val == 0.0 or val == 1.0:
                self.variables[var] = val
            else:
                print(f"Invalid BOOL value: {value}. Must be 0 or 1 (or 0.0 or 1.0).")
        except ValueError:
            print(f"Invalid BOOL value: {value}. Must be 0 or 1 (or 0.0 or 1.0).")

    def handle_python(self, code):
        try:
            if code.startswith('"') and code.endswith('"'):
                code = code[1:-1]
            env = {
                'variables': self.variables,
                'ram': self.ram,
                'print': print,
                'int': int,
                'float': float,
                'str': str,
                'bool': bool,
                'len': len,
                'range': range,
                # Add network libraries if available
                'requests': requests,
                'BeautifulSoup': BeautifulSoup,
                'html2text': html2text, # NEW: Make html2text available in PYTHON env
            }
            exec(code, env)
        except Exception as e:
            print(f"Python execution error: {e}")

    def handle_jump(self, target_line):
        try:
            target_line_int = int(target_line)
            if self.script_lines is None:
                print("JUMP command is only valid when running a script from a file.")
                return

            jump_to_index = target_line_int - 1

            if 0 <= jump_to_index < len(self.script_lines):
                self.program_counter = jump_to_index
            else:
                print(f"JUMP error: Target line {target_line_int} is out of bounds.")
        except ValueError:
            print(f"JUMP error: Invalid line number '{target_line}'. Must be a numeric value.")
        except Exception as e:
            print(f"JUMP error: {str(e)}")

    def handle_input(self, var_name):
        """Handle INPUT command: prompts user for input and stores it in var_name."""
        prompt = f"Enter value for {var_name}: "
        user_input = input(prompt)
        try:
            self.variables[var_name] = float(user_input)
        except ValueError:
            self.variables[var_name] = user_input
        print(f"'{user_input}' stored in '{var_name}'.")

    # --- File System Commands ---
    def handle_cd(self, directory_path):
        """Changes the current working directory."""
        try:
            import os
            if directory_path.startswith('"') and directory_path.endswith('"'):
                directory_path = directory_path[1:-1]
            os.chdir(directory_path)
            print(f"Changed directory to: {os.getcwd()}")
        except FileNotFoundError:
            print(f"Error: Directory '{directory_path}' not found.")
        except NotADirectoryError:
            print(f"Error: '{directory_path}' is not a directory.")
        except Exception as e:
            print(f"ET error: {e}")

    def handle_ls(self, flag, directory_path=''):
        """Lists directory contents."""
        try:
            import os
            flag_int = int(flag) # Ensure flag is interpreted as integer
            if directory_path.startswith('"') and directory_path.endswith('"'):
                directory_path = directory_path[1:-1]
            
            target_dir = directory_path if directory_path else os.getcwd()

            if not os.path.isdir(target_dir):
                print(f"Error: Directory '{target_dir}' not found.")
                return

            contents = os.listdir(target_dir)
            
            for item in sorted(contents):
                if flag_int == 1 or not item.startswith('.'): # List hidden if flag is 1
                    full_path = os.path.join(target_dir, item)
                    if os.path.isdir(full_path):
                        print(f"D {item}")
                    elif os.path.isfile(full_path):
                        print(f"F {item}")
                    else:
                        print(f"? {item}")
        except ValueError:
            print(f"LI error: Invalid flag '{flag}'. Use 0 or 1.")
        except Exception as e:
            print(f"LI error: {e}")

    # --- Network Commands ---
    def handle_network_fetch(self, url, raw_response_var, client_agent_val, format_val, language_val, decode_type_val, decoded_output_var):
        """
        Handles the FCH/FETCH command for network requests with integrated decoding.
        url: The URL to fetch (string).
        raw_response_var: Variable name to store the raw response text.
        client_agent_val: User-Agent header value (string or "TCHOA").
        format_val: Expected content format (e.g., "HTML", "JSON", or "NULL").
        language_val: Language to request (e.g., "en-US", "ar-LB", or "NULL").
        decode_type_val: "HTML" for BeautifulSoup prettify, "TEXT" for html2text, "RAW"/"NONE"/"NULL" for raw copy.
        decoded_output_var: Variable name to store the decoded/prettified content.
        """
        if requests is None:
            print("NETWORK_FETCH error: 'requests' library is not installed. Cannot perform network operations.")
            self.variables[raw_response_var] = "ERROR: requests lib missing"
            if decoded_output_var != "NULL": 
                self.variables[decoded_output_var] = "ERROR: requests lib missing"
            return

        headers = {}
        processed_url = str(url)

        # Client-Agent Header Logic
        if client_agent_val != "NULL":
            if str(client_agent_val).upper() == "TCHOA":
                headers['User-Agent'] = "TechOS-Client/1.0 SPiD-Engine/1.0 (+https://github.com/BryOfficial82/TechOS/blob/main/Main-Parser-1.0.py)" # Example custom header
                print("Client-Agent: TechOS custom header assigned.")
            else:
                headers['User-Agent'] = str(client_agent_val)
                print(f"Client-Agent: Custom header '{client_agent_val}' assigned.")
        else:
            print("Client-Agent: Default header will be used.")

        # Format Header Logic (Accept header)
        if format_val != "NULL":
            format_val_upper = str(format_val).upper()
            if format_val_upper == "HTML":
                headers['Accept'] = 'text/html, application/xhtml+xml, application/xml;q=0.9, */*;q=0.8'
                print("Format: Requesting HTML content.")
            elif format_val_upper == "JSON":
                headers['Accept'] = 'application/json'
                print("Format: Requesting JSON content.")
            else:
                headers['Accept'] = str(format_val)
                print(f"Format: Requesting custom content type '{format_val}'.")
        else:
            print("Format: No specific format requested.")

        # NEW: Language Header Logic (Accept-Language)
        if language_val != "NULL":
            headers['Accept-Language'] = str(language_val)
            print(f"Language: Requesting content in '{language_val}'.")
        else:
            print("Language: No specific language requested.")

        try:
            print(f"Fetching from: {processed_url}")
            response = requests.get(processed_url, headers=headers, timeout=10)
            response.raise_for_status()

            self.variables[raw_response_var] = str(response.text) 
            print(f"Fetched content stored in '{raw_response_var}'. (Length: {len(self.variables[raw_response_var])} bytes)")

            # Handle post-processing based on decode_type_val
            processed_content = None # To hold the result of decoding
            decode_type_upper = str(decode_type_val).upper() # Normalize for comparison

            if decoded_output_var == "NULL":
                print("Decoding skipped: No variable provided for decoded content.")
            elif decode_type_upper == "HTML":
                if BeautifulSoup is None:
                    print("NETWORK_FETCH warning: BeautifulSoup4 library not found. HTML prettification skipped.")
                    self.variables[decoded_output_var] = "Error: BeautifulSoup4 not available."
                elif str(format_val).upper() == "HTML": # BeautifulSoup expects HTML input
                    try:
                        soup = BeautifulSoup(self.variables[raw_response_var], 'html.parser')
                        processed_content = str(soup.prettify())
                        print(f"HTML prettified content stored in '{decoded_output_var}'.")
                    except Exception as parse_e:
                        self.variables[decoded_output_var] = f"Error during HTML parsing: {parse_e}"
                        print(f"NETWORK_FETCH error: Failed to parse HTML for prettification: {parse_e}")
                else:
                    print(f"NETWORK_FETCH warning: HTML prettification requested, but format '{format_val}' is not HTML. Decoding skipped.")
                    self.variables[decoded_output_var] = "Decoding skipped: Not HTML format for prettification."
            elif decode_type_upper == "TEXT":
                if html2text is None:
                    print("NETWORK_FETCH warning: 'html2text' library not found. Text decoding skipped.")
                    self.variables[decoded_output_var] = "Error: html2text not available."
                elif str(format_val).upper() == "HTML": # html2text expects HTML input
                    try:
                        h = html2text.HTML2Text()
                        # Configure html2text for clean terminal output by default
                        h.ignore_links = True
                        h.ignore_images = True
                        h.ignore_tables = True
                        h.body_width = 80 # Optional: wrap lines for better readability
                        processed_content = h.handle(self.variables[raw_response_var])
                        print(f"HTML converted to text content stored in '{decoded_output_var}'.")
                    except Exception as text_e:
                        self.variables[decoded_output_var] = f"Error during text conversion: {text_e}"
                        print(f"NETWORK_FETCH error: Failed to convert to text: {text_e}")
                else:
                    print(f"NETWORK_FETCH warning: Text decoding requested, but format '{format_val}' is not HTML. Decoding skipped.")
                    self.variables[decoded_output_var] = "Decoding skipped: Not HTML format for text conversion."
            elif decode_type_upper in ["NONE", "RAW", "NULL"]: 
                # If "RAW", "NONE", or "NULL" specified, copy raw content to the decoded_output_var if it's not NULL
                if decoded_output_var != "NULL":
                    processed_content = self.variables[raw_response_var] # Copy raw content
                    print(f"Raw content copied to '{decoded_output_var}'.")
            else:
                print(f"NETWORK_FETCH warning: Unknown decoding type '{decode_type_val}'. Decoding skipped for '{decoded_output_var}'.")
                self.variables[decoded_output_var] = f"Unknown decode type: {decode_type_val}"

            # Finally, assign the processed content if it was generated and target var is not NULL
            if processed_content is not None and decoded_output_var != "NULL":
                self.variables[decoded_output_var] = processed_content
            elif processed_content is None and decoded_output_var != "NULL":
                # If a decode type was specified but no content was produced (e.g., wrong format, or unknown type)
                # and it's not already an error message, explicitly set it to indicate no processed content.
                if decoded_output_var not in self.variables or not isinstance(self.variables[decoded_output_var], str) or not self.variables[decoded_output_var].startswith("Error"):
                    self.variables[decoded_output_var] = "NULL_CONTENT" # Explicitly indicate no processed content
            
        except requests.exceptions.RequestException as req_e:
            print(f"NETWORK_FETCH error: Network request failed: {req_e}")
            self.variables[raw_response_var] = f"Network Error: {req_e}"
            if decoded_output_var != "NULL":
                 self.variables[decoded_output_var] = "Parsing Skipped due to network error."
        except Exception as e:
            print(f"NETWORK_FETCH unexpected error: {e}")
            self.variables[raw_response_var] = f"Unexpected Error: {e}"
            if decoded_output_var != "NULL":
                 self.variables[decoded_output_var] = "Parsing Skipped due to unexpected error."

    def run(self):
        if self.script_lines:
            self.program_counter = 0
            while self.program_counter < len(self.script_lines):
                original_program_counter = self.program_counter

                line = self.script_lines[self.program_counter]
                print(f"[{self.program_counter + 1}] SPiD> {line}")
                self.execute_line(line)

                if self.program_counter == original_program_counter:
                    self.program_counter += 1
        else:
            print("[ FATAL ] All methods failed, fallbacking to shell.")
            print("SPiD OS - Type 'exit' to quit")
            while True:
                try:
                    line = input("SPiD> ")
                    if line.lower() == 'whoami':
                        print("--System Main SPiD--")
                    elif line.lower() == 'ls': # Keep fallback for direct shell 'ls' to clarify usage
                        print("[ WARNING ] Use the 'LI' command with flags for listing files.")
                    elif line.lower() == 'dir': # Keep fallback for direct shell 'dir'
                        print("[ WARNING ] Use the 'LI' command with flags for listing files.")
                    elif line.lower() == 'cd': # Keep fallback for direct shell 'cd'
                        print("[ WARNING ] Use the 'ET' command for changing directories.")
                    elif line.lower() == 'run':
                        print("[     W.I.P     ] Run is not implemented yet, try running your code directly on boot.")
                    elif line.lower() == 'exit':
                        break
                    else:
                        self.execute_line(line)
                except KeyboardInterrupt:
                    print("\nExiting...")
                    break
                except Exception as e:
                    print(f"Error: {e}")

# --- Main execution logic with hardcoded script override ---
if __name__ == "__main__":
    hardcoded_script = """
<TARGET_URL = "https://httpbin.org/user-agent">
<RAW_PAGE = "">
<CLEAN_TEXT = "">
FCH TARGET_URL RAW_PAGE "TCHOA" "HTML" "en-US,en,q=0.9" "TEXT" CLEAN_TEXT
PRINT 1 "--- Fetched content (EN-US, Text Only) ---"
PRINT 0 CLEAN_TEXT
# You can optionally print the raw data if you ever need to debug,
# but it won't be displayed with the above commands.
# PRINT 1 "--- Raw Page Content (for debugging) ---"
# PRINT 0 RAW_PAGE
"""
    script_file_path = None
    if len(sys.argv) > 1:
        script_file_path = sys.argv[1]

    if script_file_path:
        try:
            with open(script_file_path, 'r') as f:
                script_lines = [line.strip() for line in f if line.strip() and not line.strip().startswith('#')]
            interpreter = SPiDInterpreter(script_lines=script_lines)
            print(f"SPiD OS - Running script from file: {script_file_path}")
            interpreter.run()
        except FileNotFoundError:
            print(f"Error: File '{script_file_path}' not found. Attempting hardcoded script as fallback.")
            fallback_script_lines = [line.strip() for line in hardcoded_script.strip().split('\n') if line.strip() and not line.strip().startswith('#')]
            interpreter = SPiDInterpreter(script_lines=fallback_script_lines)
            print("SPiD OS - Running hardcoded fallback script.")
            interpreter.run()
        except Exception as e:
            print(f"Error loading script from file: {e}. Attempting hardcoded script as fallback.")
            fallback_script_lines = [line.strip() for line in hardcoded_script.strip().split('\n') if line.strip() and not line.strip().startswith('#')]
            interpreter = SPiDInterpreter(script_lines=fallback_script_lines)
            print("SPiD OS - Running hardcoded fallback script.")
            interpreter.run()
    else:
        print("SPiD OS - No script file specified. Running hardcoded default script.")
        fallback_script_lines = [line.strip() for line in hardcoded_script.strip().split('\n') if line.strip() and not line.strip().startswith('#')]
        interpreter = SPiDInterpreter(script_lines=fallback_script_lines)
        interpreter.run()
