# preprocessor_plugins.py
# Written by Sam Windell
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 2
# of the License, or (at your option) any later version:
# http://www.gnu.org/licenses/gpl-2.0.html
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.


#=================================================================================================
# IDEAS:
#   -   += -=
#   -   UI functions to receive arguments in any order: set_bounds(slider, width := 50, x := 20)

# BUG: commas in strings in list blocks. Can't replicate it?
import copy

import re
import math
import collections
import ksp_compiler
from simple_eval import SimpleEval
import time

#=================================================================================================
# Regular expressions
var_prefix_re = r"[%!@$]"

string_or_placeholder_re =  r'({\d+}|\"[^"]*\")'
varname_re_string = r'((\b|[$%!@])[0-9]*[a-zA-Z_][a-zA-Z0-9_]*(\.[a-zA-Z_0-9]+)*)\b'
variable_name_re = r'(?P<whole>(?P<prefix>\b|[$%!@])(?P<name>[a-zA-Z_][a-zA-Z0-9_\.]*))\b'
variable_or_int = r"[^\]]+"

commas_not_in_parenth = re.compile(r",(?![^\(\)\[\]]*[\)\]])") # All commas that are not in parenthesis.
list_add_re = re.compile(r"^\s*list_add\s*\(")

# 'Regular expressions for 'blocks'
for_re = re.compile(r"^((\s*for)(\(|\s+))")
end_for_re = re.compile(r"^\s*end\s+for")
while_re = re.compile(r"^((\s*while)(\(|\s+))")
end_while_re = re.compile(r"^\s*end\s+while")
if_re = re.compile(r"^\s*if(\s+|\()")
end_if_re = re.compile(r"^\s*end\s+if")
init_re = r"^\s*on\s+init"

pers_keyword = "pers" # The keyword that will make a variable persistent.
read_keyword = "read" # The keyword that will make a variable persistent and then read the persistent value.
concat_syntax = "concat" # The name of the function to concat arrays.

multi_dim_ui_flag = " { UI ARRAY }"

ui_type_re = r"\b(?P<uitype>ui_button|ui_switch|ui_knob|ui_label|ui_level_meter|ui_menu|ui_slider|ui_table|ui_text_edit|ui_waveform|ui_value_edit)\b"
keywords_re = r"(?<=)(declare|const|%s|%s|polyphonic|list)(?=\s)" % (pers_keyword, read_keyword)

any_pers_re = r"(%s\s+|%s\s+)" % (pers_keyword, read_keyword)
persistence_re = r"(?:\b(?P<persistence>%s|%s)\s+)?" % (pers_keyword, read_keyword)
pers_re = r"\b%s\b" % pers_keyword
read_re = r"\b%s\b" % read_keyword

define_re = r"^define\s+%s\s*(?:\((?P<args>.+)\))?\s*:=(?P<val>.+)$" % variable_name_re
const_block_start_re = r"^const\s+%s$" % variable_name_re
const_block_end_re = r"^end\s+const$"
const_block_member_re = r"^%s(?:$|\s*\:=\s*(?P<value>.+))" % variable_name_re
list_block_start_re = r"^list\s*%s\s*(?:\[(?P<size>%s)?\])?$" % (variable_name_re, variable_or_int)
list_block_end_re = r"^end\s+list$"
array_concat_re = r"(?P<declare>^\s*declare\s+)?%s\s*(?P<brackets>\[(?P<arraysize>.*)\])?\s*:=\s*%s\s*\((?P<arraylist>[^\)]*)" % (variable_name_re, concat_syntax)
ui_array_re = r"^declare\s+%s%s\s+%s\s*\[(?P<arraysize>[^\]]+)\]\s*(?P<uiparams>(?P<tablesize>\[[^\]]+\]\s*)?\(.*)?" % (persistence_re, ui_type_re, variable_name_re)


family_start_re = r"^family\s+.+"
family_end_re = r"^end\s+family$"
init_callback_re = r"^on\s+init$"
end_on_re = r"^end\s+on$"


maths_string_evaluator = SimpleEval()


#=================================================================================================
# This function is called before the macros have been expanded.
def pre_macro_functions(lines):
	remove_print(lines)
	handleDefineConstants(lines)
	handle_define_literals(lines)
	#handle_define_lines(lines)
	# handle_iterate_macro(lines)
	t = time.time()
	handleIterateMacro(lines)
	print("iterate time: %.3f" % (time.time() - t))
	handle_literate_macro(lines)

# This function is called after the macros have been expanded.
def post_macro_functions(lines):
	handle_structs(lines)
	# for line_obj in lines:
	# 	print(line_obj.command)
	# callbacks_are_functions(lines)
	incrementor(lines)
	handle_const_block(lines)
	handle_ui_arrays(lines)
	inline_declare_assignment(lines)
	multi_dimensional_arrays(lines)
	find_list_block(lines)
	# for line_obj in lines:
	# 	print(line_obj.command)
	calculate_open_size_array(lines)
	handle_lists(lines)
	variable_persistence_shorthand(lines)
	ui_property_functions(lines)
	expand_string_array_declaration(lines)  
	handle_array_concatenate(lines)

# Take the original deque of line objects, and for every new line number, add in the line_inserts.
def replace_lines(lines, line_nums, line_inserts):
	new_lines = collections.deque() # Start with an empty deque and build it up.
	# Add the text from the start of the file to the first line number we want to insert at.
	for i in range(0, line_nums[0] + 1):
		new_lines.append(lines[i])

	# For each line number insert any additional lines.
	for i in range(len(line_nums)):
		new_lines.extend(line_inserts[i])
		# Append the lines between the line_nums.
		if i + 1 < len(line_nums):
			for ii in range(line_nums[i] + 1, line_nums[i + 1] + 1):
				new_lines.append(lines[ii])

	# Add the text from the last line_num to the end of the document.
	for i in range(line_nums[len(line_nums) - 1] + 1, len(lines)):
		new_lines.append(lines[i])

	# Replace lines with new lines.
	for i in range(len(lines)):
		lines.pop()
	lines.extend(new_lines) 

# Evaluates a string of add operations, any add pairs that cannot be evalutated are left.
# e.g. "2 + 2 + 3 + 4 + x + y + 2" => "11 + x + y + 2"
def simplify_maths_addition(string):
	parts = string.split("+")
	count = 0
	while count < len(parts) - 1:
		try:
			simplified = int(parts[count]) + int(parts[count+1])
			parts[count] = str(simplified)
			parts.remove(parts[count + 1])
		except:
			count += 1
			pass
	return("+".join(parts))

def try_evaluation(expression, line, name):
	try:
		final = maths_string_evaluator.eval(str(expression).strip())
	except:
		raise ksp_compiler.ParseException(line, 
			"Invalid syntax in %s value. Only define constants, numbers or maths operations can be used here." % name)		

	return (final)

def replaceLines(original, new):
	original.clear()
	original.extend(new) 

# I think this is too clunky at the moment, it's inefficent for functions for each callback to be generated.
# def callbacks_are_functions(lines):
#   in_block = False
#   callback_name = None
#   new_lines = collections.deque()
#   for i in range(len(lines)):
#       line = lines[i].command.strip()
#       if re.search(r"^on\s+\w+(\s*\(.+\))?$", line) and not re.search(init_re, line):
#           in_block = True
#           callback_name = lines[i]
#           function_name = re.sub(r"(\s|\()", "_", line)
#           function_name = re.sub(r"\)", "", function_name)
#           new_lines.append(lines[i].copy("function " + function_name))
#       elif in_block and re.search(r"^end\s+on$", line):
#           in_block = False
#           new_lines.append(lines[i].copy("end function"))
#           new_lines.append(callback_name)
#           new_lines.append(lines[i].copy(function_name))
#           new_lines.append(callback_name.copy("end on"))
#       else:
#           new_lines.append(lines[i])
	
#   for i in range(len(lines)):
#       lines.pop()
#   lines.extend(new_lines) 


class StructMember(object):
	def __init__(self, name, command, prefix):
		self.name = name
		self.command = command
		self.prefix = prefix # The prefix symbol of the member (@!%$)
		self.numElements = None

	# numElements is a string of any amount of numbers seperated by commas
	def makeMemberAnArray(self, numElements):
		cmd = self.command
		if "[" in self.command:
			bracketLocation = cmd.find("[")
			self.command = cmd[: bracketLocation + 1] + numElements + ", " + cmd[bracketLocation + 1 :]
		else:
			self.command = re.sub(r"\b%s\b" % self.name, "%s[%s]" % (self.name, numElements), cmd)
		if self.prefix == "@":
			self.prefix = "!"

	def addNamePrefix(self, namePrefix):
		self.command = re.sub(r"\b%s\b" % self.name, "%s%s.%s" % (self.prefix, namePrefix, self.name), self.command)

class Struct(object):
	def __init__(self, name):
		self.name = name
		self.members = []

	def addMember(self, memberObj):
		self.members.append(memberObj)

	def deleteMember(self, index):
		del self.members[index]

	def insertMember(self, location, memberObj):
		self.members.insert(location, memberObj)

def handle_structs(lines):
	struct_syntax = "\&"
	structs = [] 

	# Find all the struct blocks and build struct objects of them
	inStructFlag = False
	for lineIdx in range(len(lines)):
		line = lines[lineIdx].command.strip()
		m = re.search(r"^struct\s+%s$" % varname_re_string, line)
		if m:
			structObj = Struct(m.group(1))
			if inStructFlag:
				raise ksp_compiler.ParseException(lines[lineIdx], "Struct definitions cannot be nested.\n")    
			inStructFlag = True
			lines[lineIdx].command = ""

		elif re.search(r"^end\s+struct$", line):
			inStructFlag = False
			structs.append(structObj)
			lines[lineIdx].command = ""
			
		elif inStructFlag:
			if line:
				if not line.startswith("declare ") and not line.startswith("declare	"):
					raise ksp_compiler.ParseException(lines[lineIdx], "Structs may only consist of variable declarations.\n")
				#variableName = isolate_variable_name(line).strip()
				# NOTE: experimental - see persistence function
				m = re.search(r"%s\s*(?=[\[\(\:]|$)" % variable_name_re, line)
				if m:
					variableName = m.group("whole")
					structDeclMatch = re.search(r"\&\s*%s" % variable_name_re, line)
					if structDeclMatch:
						variableName = "%s%s %s" % ("&", structDeclMatch.group("whole"), variableName)
				prefixSymbol = ""
				if re.match(var_prefix_re, variableName):
					prefixSymbol = variableName[:1]
					variableName = variableName[1:]
				structObj.addMember(StructMember(variableName, line.replace("%s%s" % (prefixSymbol, variableName), variableName), prefixSymbol))
			lines[lineIdx].command = ""

	if structs:
		# Make the struct names a list so they are easily searchable
		structNames = [structs[i].name for i in range(len(structs))]

		for i in range(len(structs)):
			j = 0
			counter = 0
			stillRemainginStructs = False
			# Cycle through the members of each struct and resolve all members that are struct declarations
			while j < len(structs[i].members) or stillRemainginStructs == True:
				m = re.search(r"^([^%s]+\.)?%s\s*%s\s+%s" % (struct_syntax, struct_syntax, varname_re_string, varname_re_string), structs[i].members[j].name)
				if m:
					structs[i].deleteMember(j)
					structNum = structNames.index(m.group(2))
					structVariable = m.group(5).strip()
					if m.group(1):
						structVariable = m.group(1) + structVariable
					if structNum == i:
						raise ksp_compiler.ParseException(lines[0], "Declared struct cannot be the same as struct parent.\n")

					insertLocation = j
					for memberIdx in range(len(structs[structNum].members)):
						structMember = structs[structNum].members[memberIdx]
						var_name = structVariable + "." + structMember.name
						new_command = re.sub(r"\b%s\b" % structMember.name, var_name, structMember.command)
						structs[i].insertMember(insertLocation, StructMember(var_name, new_command, structMember.prefix))
						insertLocation += 1
					for name in structs[i].members[j].name:
						mm = re.search(r"^(?:[^%s]+\.)?%s\s*%s\s+%s" % (struct_syntax, struct_syntax, varname_re_string, varname_re_string), name)
						if mm:
							stillRemainginStructs = True
				j += 1

				if j >= len(structs[i].members) and stillRemainginStructs:
					stillRemainginStructs = False
					j = 0
					counter += 1
					if counter > 100000:
						raise ksp_compiler.ParseException(lines[0], "ERROR! Too many iterations while building structs.")
						break

		newLines = collections.deque()
		for i in range(len(lines)):
			line = lines[i].command.strip()
			m = re.search(r"^declare\s+%s\s*%s\s+%s(?:\[(.*)\])?$" % (struct_syntax, varname_re_string, varname_re_string), line)
			if m:
				structName = m.group(1)
				declaredName = m.group(4)
				try:
					structIdx = structNames.index(structName)
				except ValueError:
					raise ksp_compiler.ParseException(lines[i], "Undeclared struct %s\n" % structName)

				newMembers = copy.deepcopy(structs[structIdx].members)
				# If necessary make the struct members into arrays.
				arrayNumElements = m.group(7)
				if arrayNumElements:
					for j in range(len(newMembers)):
						newMembers[j].makeMemberAnArray(arrayNumElements)
					if "," in arrayNumElements:
						arrayNumElements = ksp_compiler.split_args(arrayNumElements, lines[i])
						for dimIdx in range(len(arrayNumElements)):
							newLines.append(lines[i].copy("declare const %s.SIZE_D%d := %s" % (declaredName, dimIdx + 1, arrayNumElements[dimIdx])))
					else:
						newLines.append(lines[i].copy("declare const %s.SIZE := %s" % (declaredName, arrayNumElements)))


				# Add the declared names as a prefix and add the memebers to the newLines deque
				for j in range(len(newMembers)):
					newMembers[j].addNamePrefix(declaredName)

					newLines.append(lines[i].copy(newMembers[j].command))
			else:
				newLines.append(lines[i])

		replaceLines(lines, newLines)
		


# Remove print functions when the activate_logger() is not present.
def remove_print(lines):
	print_line_numbers = []
	logger_active_flag = False
	for i in range(len(lines)):
		line = lines[i].command.strip()
		if re.search(r"^activate_logger\s*\(", line):
			logger_active_flag = True
		if re.search(r"^print\s*\(", line):
			print_line_numbers.append(i)

	if not logger_active_flag:
		for i in range(len(print_line_numbers)):
			lines[print_line_numbers[i]].command = ""

def incrementor(lines):
	start_keyword = "START_INC"
	end_keyword = "END_INC"
	names = []
	it_vals = []
	step = []

	for i in range(len(lines)):
		line = lines[i].command
		m = re.search(r"^\s*%s\s*\(" % start_keyword, line)
		if m:
			mm = re.search(r"^\s*%s\s*\(\s*%s\s*\,\s*(.+)s*\,\s*(.+)\s*\)" % (start_keyword, varname_re_string), line)
			if mm:
				lines[i].command = ""
				names.append(mm.group(1))
				it_val = try_evaluation(mm.group(4), lines[i], "start")
				step_val = try_evaluation(mm.group(5), lines[i], "step")
				it_vals.append(it_val)
				step.append(step_val)
			else:
				raise ksp_compiler.ParseException(lines[i], "Incorrect parameters. Expected: START_INC(<name>, <num-or-define>, <num-or-define>)\n")    
		elif re.search(r"^\s*%s" % end_keyword, line):
			lines[i].command = ""
			names.pop()
			it_vals.pop()
			step.pop()
		elif names:
			for j in range(len(names)):
				mm = re.search(r"\b%s\b" % names[j], line)
				if mm:
					# lines[i].command = line.replace(names[j], str(it_vals[j]))
					lines[i].command = re.sub(r"\b%s\b" % names[j], str(it_vals[j]), lines[i].command)
					it_vals[j] += step[j]


# Function for concatenating multiple arrays into one. 
def handle_array_concatenate(lines):
	line_numbers = []
	parent_array = []
	child_arrays = []
	num_args     = []
	init_line_num = None

	for i in range(len(lines)):
		line = lines[i].command
		if re.search(init_re, line):
			init_line_num = i
		m = re.search(array_concat_re, line)
		#r"(?P<declare>^\s*declare\s+)?%s\s*(?P<brackets>\[(?P<arraysize>.*)\])?\s*:=\s*%s\s*\((?P<arraylist>[^\)]*)" % (variable_name_re, concat_syntax)
		if m:
			search_list = m.group("arraylist").split(",")
			# Why doesn't this work? It seems to make makes all previous lists in child_arrays empty. Extend seems to work, but
			# append doesn't. This has been bodged for now.
			# child_arrays.append(search_list)
			child_arrays.extend(search_list)
			parent_array.append(m.group("whole"))
			num_args.append(len(search_list))
			line_numbers.append(i)
			size = None
			if re.search(r"\bdeclare\b", line):
				if not m.group("brackets"):
					raise ksp_compiler.ParseException(lines[i], "No array size given. Leave brackets [] empty to have the size auto generated.\n")  
				if not m.group("arraysize"):
					sizes = []
					for j in range(0, i):
						line2 = lines[j].command
						for arg in search_list:
							try: # The regex doesn't like it when there are [] or () in the arg list.
								mm = re.search(r"^\s*declare\s+%s?%s\s*(\[.*\])" % (var_prefix_re, arg.strip()), line2)
								if mm:
									sizes.append(mm.group(1))
									search_list.remove(arg)
									break
							except:
								raise ksp_compiler.ParseException(lines[i], "Syntax error.\n") 
					if search_list:  # If everything was found, then the list will be empty.
						raise ksp_compiler.ParseException(lines[i], "Undeclared array(s) in %s function: %s\n" % (concat_syntax, ', '.join(search_list).strip()))
					size = simplify_maths_addition(re.sub(r"[\[\]]", "", '+'.join(sizes)))
				else:
					size = m.group("arraysize")
				lines[i].command = "declare %s[%s]" % (m.group("whole"), size) 
			else:
				lines[i].command = ""

	if line_numbers:
		line_inserts = collections.deque()
		for i in range(len(line_numbers)):
			added_lines = []
			
			# We have to calculate the start and end points in the arg list, because the append isn't working.
			s = 0
			if i != 0:
				for j in range(i):
					s += num_args[j]

			offsets = ["0"]
			for j in range(s, s + num_args[i]):
				offsets.append("num_elements(%s)" % child_arrays[j])

			add_offset = ""
			if num_args[i] != 1:
				add_offset = " + concat_offset"
				added_lines.append(lines[line_numbers[i]].copy("concat_offset := 0"))

			offset_command = "concat_offset := concat_offset + #offset#"
			template_text = [
			"for concat_it := 0 to num_elements(#arg#)-1",
			"   #parent#[concat_it%s] := #arg#[concat_it]" % add_offset,
			"end for"]

			for j in range(num_args[i]):
				if j != 0 and num_args[i] != 1:
					current_text = offset_command.replace("#offset#", offsets[j])
					added_lines.append(lines[line_numbers[i]].copy(current_text))
				for text in template_text:
					current_text = text.replace("#arg#", child_arrays[s + j]).replace("#parent#", parent_array[i])
					added_lines.append(lines[line_numbers[i]].copy(current_text))

			line_inserts.append(added_lines)
		replace_lines(lines, line_numbers, line_inserts)

		# Add declare variables at the start on the init callback.
		new_lines = collections.deque()
		for i in range(0, init_line_num + 1):
			new_lines.append(lines[i])

		new_lines.append(lines[init_line_num].copy("    declare concat_it"))
		new_lines.append(lines[init_line_num].copy("    declare concat_offset"))
		for i in range(init_line_num + 1, len(lines)):
			new_lines.append(lines[i])

		replaceLines(lines, new_lines)

# If the given line is in at least 1 family, return the family prefixes.
def inspect_family_state(lines, text_lineno):
	current_family_names = []
	for i in range(len(lines)):
		if i == text_lineno:
			if current_family_names:
				return (".".join(current_family_names) + ".")
			else:
				return (None)
			break
		line = lines[i].command.strip()
		m = re.search(r"^family\s+(.+)$", line)
		if m:
			current_family_names.append(m.group(1))
		elif re.search(r"^end\s+family$", line):
			current_family_names.pop()


#=================================================================================================
class MultiDimensionalArray(object):
	def __init__(self, name, prefix, dimensions_string, persistence, assignment, family_prefix, line):
		self.name = name
		self.prefix = prefix or ""
		self.assignment = assignment or ""
		self.dimensions = ksp_compiler.split_args(dimensions_string, line) # TODO: check spilt args, what about commas_not_in_paren
		self.persistence = persistence or ""
		self.raw_array_name = family_prefix + "_" + self.name

	def get_raw_array_declaration(self):
		new_name = self.prefix + "_" + self.name
		total_array_size = "*".join(["(" + dim + ")" for dim in self.dimensions])
		return("declare %s %s [%s] %s" % (self.persistence, new_name, total_array_size, self.assignment))

	def build_property_and_constants(self, line):
		property_template = [
		"property #propName#",
			"function get(#dimList#) -> result",
				"result := #rawArrayName#[#calculatedDimList#]",
			"end function",
			"function set(#dimList#, val)",
				"#rawArrayName#[#calculatedDimList#] := val",
			"end function ",
		"end property"]		
		const_template = "declare const #name#.SIZE_D#dimNum# := #val#"

		new_lines = collections.deque()
		# Build the declare const lines and add them to the new_line deque.
		for dim_num, dim_size in enumerate(self.dimensions):
			declare_const_text = const_template\
				.replace("#name#", self.name)\
				.replace("#dimNum#", str(dim_num + 1))\
				.replace("#val#", dim_size)
			new_lines.append(line.copy(declare_const_text))
		# Build the list of arguments, eg: "d1, d2, d3"
		dimension_arg_list = ["d" + str(dim_num + 1) for dim_num in range(len(self.dimensions))]
		dimension_arg_string = ",".join(dimension_arg_list)
		# Create the maths for mapping multiple dimensions to a single dimension array, eg: "d1 * (20) + d2"
		num_dimensions = len(self.dimensions)
		calculated_dim_list = []
		for dim_num in range(num_dimensions - 1):
			for i in range(num_dimensions - 1, dim_num, -1):
				calculated_dim_list.append("(%s) * " % self.dimensions[i])
			calculated_dim_list.append(dimension_arg_list[dim_num] + " + ")
		calculated_dim_list.append(dimension_arg_list[num_dimensions - 1])
		calculated_dimensions = "".join(calculated_dim_list)
		for prop_line in property_template:
			property_text = prop_line\
				.replace("#propName#", self.name)\
				.replace("#dimList#", dimension_arg_string)\
				.replace("#rawArrayName#", self.raw_array_name)\
				.replace("#calculatedDimList#", calculated_dimensions)
			new_lines.append(line.copy(property_text))
		return(new_lines)

# TODO: Check whether making this only init callback is ok.
def multi_dimensional_arrays(lines):
	multiple_dimensions_re = r"\[(?P<dimensions>[^\]]+(?:\,[^\]]+)+)\]" # Match square brackets with 2 or more comma separated dimensions.
	multidimensional_array_re = r"^declare\s+%s%s\s*%s(?P<assignment>\s*:=.+)?(?P<uiArray>%s)?$" % (persistence_re, variable_name_re, multiple_dimensions_re, multi_dim_ui_flag)

	new_lines = collections.deque()
	fam_count = 0
	init_flag = False
	for line_num in range(len(lines)):
		line = lines[line_num].command.strip()
		if not init_flag:
			if re.search(init_callback_re, line):
				init_flag = True
			new_lines.append(lines[line_num])
		else: # Multidimensional arrays are only allowed in the init callback.
			if re.search(end_on_re, line):
				new_lines.extend(lines[line_num:])
				break
			else: 
				m = re.search(multidimensional_array_re, line)
				if re.search(family_start_re, line):
					fam_count += 1
				elif re.search(family_end_re, line):
					fam_count -= 1
				elif m:
					fam_prefix = ""
					if fam_count != 0:
						fam_prefix = inspect_family_state(lines, line_num)
					name = m.group("name")
					if m.group("uiArray"):
						name = name[1:] # If it is a UI array, the single dimension array will already have the underscore, so it is removed.
					multi_dim = MultiDimensionalArray(name, m.group("prefix"), m.group("dimensions"), m.group("persistence"), m.group("assignment"), fam_prefix, lines[line_num])
					new_lines.append(lines[line_num].copy(multi_dim.get_raw_array_declaration()))
					new_lines.extend(multi_dim.build_property_and_constants(lines[line_num]))
				if not m:
					new_lines.append(lines[line_num])

	replaceLines(lines, new_lines)


#===========================================================================================
class UIPropertyTemplate:
	def __init__(self, name, arg_string):
		self.name = name
		self.args = arg_string.replace(" ", "").split(",")

class UIPropertyFunction:
	def __init__(self, function_type, args, line):
		self.function_type = function_type
		self.args  = args[1:]
		if len(self.args) > len(function_type.args):
			raise ksp_compiler.ParseException(line, "Too many arguments, maximum is %d, got %d.\n" % (len(function_type.args), len(self.args)))
		elif len(self.args) == 0:
			raise ksp_compiler.ParseException(line, "Function requires at least 2 arguments.\n")
		self.ui_id = args[0]

	def build_ui_property_lines(self, line):
		new_lines = collections.deque()
		for arg_num in range(len(self.args)):
			new_lines.append(line.copy("%s -> %s := %s" % (self.ui_id, self.function_type.args[arg_num], self.args[arg_num])))
		return(new_lines)

def ui_property_functions(lines):
	# Templates for the functions. Note the ui-id as the first arg and the functions start 
	# with'set_' is assumed to be true later on.
	ui_control_property_function_templates = [
	"set_bounds(ui-id, x, y, width, height)",
	"set_slider_properties(ui-id, default, picture, mouse_behaviour)",
	"set_switch_properties(ui-id, text, picture, text_alignment, font_type, textpos_y)",
	"set_label_properties(ui-id, text, picture, text_alignment, font_type, textpos_y)",
	"set_menu_properties(ui-id, picture, font_type, text_alignment, textpos_y)",
	"set_table_properties(ui-id, bar_color, zero_line_color)",
	"set_button_properties(ui-id, text, picture, text_alignment, font_type, textpos_y)",
	"set_level_meter_properties(ui-id, bg_color, off_color, on_color, overload_color)",
	"set_waveform_properties(ui-id, bar_color, zero_line_color)",
	"set_knob_properties(ui-id, text, default)" ]

	# Use the template string above to build a list of UIProperyTemplate objects.
	ui_funcs = []
	for func_template in ui_control_property_function_templates:
		m = re.search(r"^(?P<name>[^\(]+)\(ui-id,(?P<args>[^\)]+)", func_template)
		ui_funcs.append(UIPropertyTemplate(m.group("name"), m.group("args")))

	new_lines = collections.deque()
	for line_num in range(len(lines)):
		line = lines[line_num].command.strip()
		found_prop = False
		if re.search(r"^set_", line): # Quick little check will speed things up.
			for func in ui_funcs:
				if re.search(r"^%s\b" % func.name, line):
					found_prop = True
					param_string = line[line.find("(") + 1 : len(line) - 1].strip()
					param_list = re.split(commas_not_in_parenth, param_string)
					ui_property_obj = UIPropertyFunction(func, param_list, lines[line_num])
					new_lines.extend(ui_property_obj.build_ui_property_lines(lines[line_num]))
					break
		if not found_prop:
			new_lines.append(lines[line_num])

	replaceLines(lines, new_lines)

#=================================================================================================
# When a variable is declared and initialised on the same line, check to see if the value needs to be
# moved over to the next line.
def inline_declare_assignment(lines):
	new_lines = collections.deque()
	for i in range(len(lines)):
		line = lines[i].command.strip()
		m = re.search(r"^declare\s+(?:(polyphonic|global|local)\s+)*%s%s\s*:=" % (persistence_re, variable_name_re), line)
		if m and not re.search(r"\b%s\s*\(" % concat_syntax, line):
			int_flag = False
			value = line[line.find(":=") + 2 :]
			if not re.search(string_or_placeholder_re, line):
				try:
					# Ideally this would check to see if the value is a Kontakt constant as those are valid
					# inline as well.
					eval(value) # Just used as a test to see if the the value is a constant.
					int_flag = True 
				except:
					pass

			if not int_flag:
				pre_assignment_text = line[: line.find(":=")]
				variable_name = m.group("name")
				new_lines.append(lines[i].copy(pre_assignment_text))
				new_lines.append(lines[i].copy(variable_name + " " + line[line.find(":=") :]))
			else:
				new_lines.append(lines[i])
		else:
			new_lines.append(lines[i])
	replaceLines(lines, new_lines)

#=================================================================================================
class ConstBlock(object):
	def __init__(self, name):
		self.name = name
		self.member_values = []
		self.member_names = []
		self.previous_val = "-1"

	def add_member(self, name, value):
		self.member_names.append(name)
		new_val = ""
		if value:
			new_val = value
		else:
			new_val = self.previous_val + "+1"
		new_val = simplify_maths_addition(new_val)
		self.member_values.append(new_val)
		self.previous_val = new_val

	def build_lines(self, line):
		new_lines = collections.deque()
		new_lines.append(line.copy("declare %s[%s] := (%s)" % (self.name, len(self.member_names), ", ".join(self.member_values))))
		new_lines.append(line.copy("declare const %s.SIZE := %s" % (self.name, len(self.member_names))))
		for mem_num in range(len(self.member_names)):
			new_lines.append(line.copy("declare const %s.%s := %s" % (self.name, self.member_names[mem_num], self.member_values[mem_num])))
		return(new_lines)

def handle_const_block(lines):
	new_lines = collections.deque()
	const_block_obj = None
	in_const_block = False
	for line_num in range(len(lines)):
		line = lines[line_num].command.strip()
		m = re.search(const_block_start_re, line)
		if m:
			const_block_obj = ConstBlock(m.group("name"))
			in_const_block = True
		elif re.search(const_block_end_re, line):
			new_lines.extend(const_block_obj.build_lines(lines[line_num]))
			in_const_block = False
		elif in_const_block:
			m = re.search(const_block_member_re, line)
			if m:
				const_block_obj.add_member(m.group("whole"), m.group("value"))
			elif not line.strip() == "":
				raise ksp_compiler.ParseException(lines[line_num], "Incorrect syntax. In a const block, list constant names and optionally assign them a constant value.")
		else:
			new_lines.append(lines[line_num])

	replaceLines(lines, new_lines)

#=================================================================================================
class ListBlock(object):
	def __init__(self, name, size):
		self.name = name
		self.size = size or ""
		self.is_multi_dim = False
		if size: 
			self.is_multi_dim = "," in size
		# if size:
		# 	self.size = size
		# 	self.is_multi_dim = "," in size
		self.members = []

	def add_member(self, command):
		self.members.append(command)

	# The list block just builds lines ready for the list function later on to interpret them.
	def build_lines(self, line):
		new_lines = collections.deque()
		new_lines.append(line.copy("declare list %s[%s]" % (self.name, self.size)))
		for mem_num in range(len(self.members)):
			member_name = self.members[mem_num]
			if self.is_multi_dim:
				# If the member is a comma seperated list, then we first need to assign the list to an array in kontakt
				string_list = re.search(commas_not_in_parenth, member_name)
				if string_list:
					member_name = self.name + str(mem_num)
					new_lines.append(line.copy("declare %s[] := (%s)" % (member_name, self.members[men_num])))
			new_lines.append(line.copy("list_add(%s, %s)" % (self.name, member_name)))
		return(new_lines)

def find_list_block(lines):
	new_lines = collections.deque()
	list_block_obj = None
	is_list_block = False
	for line_num in range(len(lines)):
		line = lines[line_num].command.strip()
		m = re.search(list_block_start_re, line)
		if m:
			is_list_block = True
			list_block_obj = ListBlock(m.group("whole"), m.group("size"))
		elif is_list_block and not line == "":
			if re.search(list_block_end_re, line):
				is_list_block = False
				new_lines.extend(list_block_obj.build_lines(lines[line_num]))
			else:
				list_block_obj.add_member(line)
		else:
			new_lines.append(lines[line_num])

	replaceLines(lines, new_lines)
     

def find_all_arrays(lines):
	array_names = []
	array_sizes = []
	for i in range(len(lines)):
		line = lines[i].command
		m = re.search(r"^\s*declare\s+%s?%s\s*(?:\[(%s)\])" % (any_pers_re, varname_re_string, variable_or_int), line)
		if m:
			array_names.append(re.sub(var_prefix_re, "", m.group(2)))
			array_sizes.append(m.group(5))

	return (array_names, array_sizes)

# Convert lists and list_add() into commands that Kontakt can understand.
def handle_lists(lines):
	list_names   = []
	line_numbers = []
	init_flag    = None
	loop_flag    = None
	iterators    = []
	is_matrix    = []
	init_line_num = None

	matrix_size_lists = []
	matrix_list_add_line_nums = []
	matrix_list_add_text = []
	matrix_list_flag = "{MATRIX_LIST_ADD}"

	list_add_array_template = [
	"for list_it := 0 to #size# - 1",
	"   #list#[list_it + #offset#] := #arr#[list_it]",
	"end for"]
	list_add_array_tokens = ["#size#", "#list#", "#offset#", "#arr#"]

	def replace_tokens(template, tokens, values):
		new_text = []
		for text in template:
			for i in range(len(tokens)):
				text = text.replace(tokens[i], str(values[i]))
			new_text.append(text)
		return new_text

	list_matrix_template = [
	"declare #list#.sizes[#size#] := (#sizeList#)",
	"declare #list#.pos[#size#] := (#posList#)",
	"property #list#",
	"   function get(d1, d2) -> result",
	"       result := _#list#[#list#.pos[d1] + d2]",
	"   end function",
	"   function set(d1, d2, val)",
	"       _#list#[#list#.pos[d1] + d2] := val",
	"   end function",
	"end property"]
	list_matrix_tokens = ["#list#", "#size#", "#sizeList#", "#posList#"]

	array_names, array_sizes = find_all_arrays(lines)
	# print(array_names)

	for i in range(len(lines)):
		line = lines[i].command
		# m = re.search(r"^\s*declare\s+%s?list\s*%s" % (any_pers_re, varname_re_string), line)
		m = re.search(r"^\s*declare\s+%s?list\s*%s\s*(?:\[(%s)?\])?" % (any_pers_re, varname_re_string, variable_or_int), line)     
		if re.search(r"^\s*on\s+init", line):
			init_flag = True
			init_line_num = i
		elif re.search(r"^\s*end\s+on", line):
			if init_flag:
				for ii in range(len(iterators)):
					list_declare_line = lines[line_numbers[ii]].command
					square_bracket_pos = list_declare_line.find("[]") 
					lines[line_numbers[ii]].command = list_declare_line[: square_bracket_pos + 1] + str(iterators[ii]) + "]"
				init_flag = False
		elif re.search(for_re, line) or re.search(while_re, line) or re.search(if_re, line):
			loop_flag = True
		elif re.search(end_for_re, line) or re.search(end_while_re, line) or re.search(end_if_re, line):
			loop_flag = False
		elif m:
			name = m.group(2)
			is_pers = ""
			if m.group(1):
				is_pers = " " + m.group(1)
			line_numbers.append(i)
			iterators.append("0")

			is_matrix_type = False
			if m.group(5):
				is_matrix_type = "," in m.group(5)
				if is_matrix_type:
					prefix = ""
					if m.group(3):
						prefix = m.group(3)
					name = prefix + "_" + re.sub(var_prefix_re, "", name)

			list_names.append(name)
			is_matrix.append(is_matrix_type)

			# The number of elements is populated once the whole init callback is scanned.
			lines[i].command = "declare " + is_pers + name + "[]"
		else:
			if re.search(list_add_re, line):
				find_list_name = False
				for ii in range(len(list_names)):
					list_title = re.sub(var_prefix_re, "", list_names[ii])
					if is_matrix[ii]:
						list_title = list_title[1:]
					if re.search(r"list_add\s*\(\s*%s?%s\b" % (var_prefix_re, list_title), line):
						find_list_name = True
						if loop_flag:
							raise ksp_compiler.ParseException(lines[i], "list_add() cannot be used in loops or if statements.\n")
						if not init_flag:
							raise ksp_compiler.ParseException(lines[i], "list_add() can only be used in the init callback.\n")

						value = line[line.find(",") + 1 : len(line) - 1].strip()
						value = re.sub(var_prefix_re, "", value)

						size = None
						def increase_iterator(amount):
							iterators[ii] = simplify_maths_addition(iterators[ii] + " + " + str(amount))
							return amount   

						if not is_matrix[ii] or (is_matrix[ii] and not value in array_names):
							lines[i].command = list_names[ii] + "[" + str(iterators[ii]) + "] := " + value
							size = increase_iterator(1)
						else:
							array_location = array_names.index(value)
							new_text = replace_tokens(list_add_array_template, list_add_array_tokens, [array_sizes[array_location], "_" + list_title, iterators[ii], value])
							matrix_list_add_text.append(new_text)
							matrix_list_add_line_nums.append(i)
							lines[i].command = matrix_list_flag
							size = increase_iterator(array_sizes[array_location])                       
						if is_matrix[ii]:
							matrix_size_lists.append([list_title, size])
						break
				if not find_list_name:
					undeclared_name = line[line.find("(") + 1 : line.find(",")].strip()
					raise ksp_compiler.ParseException(lines[i], undeclared_name + " had not been declared.\n") 

	if line_numbers:
		line_inserts = collections.deque()
		for i in range(len(line_numbers)):
			added_lines = []

			size_list = []
			list_name = re.sub(var_prefix_re, "", list_names[i])
			if is_matrix[i]:
				list_name = list_name[1:]
				pos_list = ["0"]
				for j in range(len(matrix_size_lists)):
					if matrix_size_lists[j][0] == list_name:
						size_list.append(str(matrix_size_lists[j][1]))
				size_counter = "0"
				for j in range(len(size_list)-1):
					size_counter = simplify_maths_addition(size_counter + "+" + size_list[j])
					pos_list.append(size_counter)
				new_text = replace_tokens(list_matrix_template, list_matrix_tokens, [list_name, str(len(size_list)), ", ".join(size_list), ", ".join(pos_list)])
				for text in new_text:
					added_lines.append(lines[line_numbers[i]].copy(text))   

			const_size = 0
			if len(size_list) == 0:
				const_size = iterators[i]
			else:
				const_size = len(size_list)

			current_text = "declare const " + list_name + ".SIZE := " + str(const_size)
			added_lines.append(lines[line_numbers[i]].copy(current_text))

			line_inserts.append(added_lines)

		replace_lines(lines, line_numbers, line_inserts)

		# Add declare variables at the start on the init callback.
		new_lines = collections.deque()
		for i in range(0, init_line_num + 1):
			new_lines.append(lines[i])

		new_lines.append(lines[init_line_num].copy("    declare list_it"))
		for i in range(init_line_num + 1, len(lines)):
			new_lines.append(lines[i])

		replaceLines(lines, new_lines)
	
	if matrix_list_add_line_nums:
		line_inserts = collections.deque()
		line_nums = []
		for i in range(len(lines)):
			if lines[i].command == matrix_list_flag:
				lines[i].command = ""
				line_nums.append(i)

		for i in range(len(line_nums)):
			added_lines = []

			text_list = matrix_list_add_text[i]
			for text in text_list:
				added_lines.append(lines[line_nums[i]].copy(text))

			line_inserts.append(added_lines)
		replace_lines(lines, line_nums, line_inserts)

		
# When an array size is left with an open number of elements, use the list of initialisers to provide the array size.
# Const variables are also generated for the array size. 
def calculate_open_size_array(lines):
	array_name = []
	line_numbers = []
	num_ele = []

	for i in range(len(lines)):
		line = lines[i].command
		ls_line = re.sub(r"\s", "", line)
		m = re.search(r"^\s*declare\s+%s?%s\s*\[\s*\]\s*:=\s*\(" % (any_pers_re, varname_re_string), line)      
		if m:
			comma_sep = ls_line[ls_line.find("(") + 1 : len(ls_line) - 1]
			string_list = re.split(commas_not_in_parenth, comma_sep)
			num_elements = len(string_list)
			# name = line[: line.find("[")].replace("declare", "").strip()
			name = m.group(2)
			name = re.sub(var_prefix_re, "", name)

			lines[i].command = line[: line.find("[") + 1] + str(num_elements) + line[line.find("[") + 1 :]

			array_name.append(name)
			line_numbers.append(i)
			num_ele.append(num_elements)

	if line_numbers:
		line_inserts = collections.deque()
		for i in range(len(line_numbers)):
			added_lines = []

			current_text = "declare const " + array_name[i] + ".SIZE := " + str(num_ele[i])
			added_lines.append(lines[line_numbers[i]].copy(current_text))

			line_inserts.append(added_lines)
		replace_lines(lines, line_numbers, line_inserts)

# Convert the single-line list of strings to one string per line for Kontakt to understand.
def expand_string_array_declaration(lines):
	string_var_names = []
	strings = []
	line_numbers = []
	num_ele = []

	for i in range(len(lines)):
		line = lines[i].command.strip()
		# Convert text array declaration to multiline
		m = re.search(r"^\s*declare\s+" + varname_re_string + r"\s*\[\s*" + variable_or_int + r"\s*\]\s*:=\s*\(\s*" + string_or_placeholder_re + r"(\s*,\s*" + string_or_placeholder_re + r")*\s*\)", line)
		if m:
			if m.group(2) == "!":
				comma_sep = line[line.find("(") + 1 : len(line) - 1]
				string_list = re.split(commas_not_in_parenth, comma_sep)
				num_elements = len(string_list)
				
				search_obj = re.search(r'\s+!' + varname_re_string, line)
				string_var_names.append(search_obj.group(0))

				num_ele.append(num_elements)
				strings.append(string_list)
				line_numbers.append(i)
			else:
				raise ksp_compiler.ParseException(lines[i], "Expected integers, got strings.\n")

	# For some reason this doesn't work in the loop above...?
	for lineno in line_numbers: 
		lines[lineno].command = lines[lineno].command[: lines[lineno].command.find(":")]

	if line_numbers:
		line_inserts = collections.deque()
		for i in range(len(line_numbers)):
			added_lines = []

			for ii in range(num_ele[i]):
				current_text = string_var_names[i] + "[" + str(ii) + "] := " + strings[i][ii] 
				added_lines.append(lines[line_numbers[i]].copy(current_text))

			line_inserts.append(added_lines)
		replace_lines(lines, line_numbers, line_inserts)


#=================================================================================================
def variable_persistence_shorthand(lines):
	newLines = collections.deque()
	famCount = 0
	isInFamily = False
	for i in range(len(lines)):
		line = lines[i].command.strip()

		if not isInFamily:
			if line.startswith("family ") or line.startswith("family	"): # startswith is faster than regex
				famCount += 1
				isInFamily = True
		elif line.startswith("end ") or line.startswith("end	"):
			famCount -= 1
			isInFamily = False

		if line.startswith("declare"):
			# NOTE: experimental - assuming the name is either the first word before a [ or ( or before the end
			# This was done because it is much faster.
			m = re.search(r"\b(?P<persistence>pers|read)\b" , line)
			if m:
				persWord = m.group("persistence")
				m = re.search(r"%s\s*(?=[\[\(]|$)" % variable_name_re, line)
				if m:
					variableName = m.group("name")
					if famCount != 0: # Counting the family state is much faster than inspecting on every line.
						famPre = inspect_family_state(lines, i)
						if famPre:
							variableName = famPre + variableName.strip()
					newLines.append(lines[i].copy(re.sub(r"\b%s\b" % persWord, "", line)))
					newLines.append(lines[i].copy("make_persistent(%s)" % variableName))
					if persWord == "read":
						newLines.append(lines[i].copy("read_persistent_var(%s)" % variableName))
				else:
					newLines.append(lines[i])
			else:
				newLines.append(lines[i])
		else:
			newLines.append(lines[i])

	replaceLines(lines, newLines)

#=================================================================================================
class IterateMacro(object):
	def __init__(self, macroName, minVal, maxVal, step, direction, line):
		self.line = line
		self.macroName = macroName
		self.isSingleLine = "#n#" in self.macroName
		self.minVal = int(try_evaluation(minVal, line, "min"))
		self.maxVal = int(try_evaluation(maxVal, line, "max"))
		self.step = 1
		if step:
			self.step = int(try_evaluation(step, line, "step"))
		self.direction = direction
		if (self.minVal > self.maxVal and self.direction == "to") or (self.minVal < self.maxVal and self.direction == "downto"):
			raise ksp_compiler.ParseException(line, "Min and max values are incorrectly weighted (For example, min > max when it should be min < max)./n")

	def buildLines(self):
		newLines = collections.deque()
		offset = 1
		if self.direction == "downto":
			self.step = -self.step
			offset = -1

		if not self.isSingleLine:
			for i in range(self.minVal, self.maxVal + offset, self.step):
				newLines.append(self.line.copy("%s(%s)" % (self.macroName, str(i))))
		else:
			for i in range(self.minVal, self.maxVal + offset, self.step):
				newLines.append(self.line.copy(self.macroName.replace("#n#", str(i))))
		return(newLines)

def handleIterateMacro(lines):
	newLines = collections.deque()
	for lineIdx in range(len(lines)):
		line = lines[lineIdx].command.strip()
		if line.startswith("iterate_macro"):
			m = re.search(r"^iterate_macro\s*\((?P<macro>.+)\)\s*:=\s*(?P<min>.+)\b(?P<direction>to|downto)(?P<max>(?:.(?!\bstep\b))+)(?:\s+step\s+(?P<step>.+))?$", line)
			if m:
				iterateObj = IterateMacro(m.group("macro"), m.group("min"), m.group("max"), m.group("step"), m.group("direction"), lines[lineIdx])
				newLines.extend(iterateObj.buildLines())
			else:
				newLines.append(lines[lineIdx])
		else:
			newLines.append(lines[lineIdx])
	replaceLines(lines, newLines)

#=================================================================================================
class DefineConstant(object):
	def __init__(self, name, value, argString, line):
		self.name = name
		self.value = value
		if self.value.startswith("#") and self.value.endswith("#"):
			self.value = self.value[1 : len(self.value) - 1]
		self.args = []
		if argString:
			self.args = ksp_compiler.split_args(argString, line)
		self.line = line
		if re.search(r"\b%s\b" % self.name, self.value):
			raise ksp_compiler.ParseException(self.line, "Define constant cannot call itself.")

	def getName(self):
		return(self.name)
	def getValue(self):
		return(self.value)
	def setValue(self, val):
		self.value = val

	def evaluateValue(self):
		newVal = self.value
		try:
			val = re.sub(r"\smod\s", " % ", self.value)
			newVal = str(maths_string_evaluator.eval(val))
		except:
			pass
		self.setValue(newVal)

	def substituteValue(self, command):
		newCommand = command
		if self.name in command:
			if not self.args:
				newCommand = re.sub(r"\b%s\b" % self.name, self.value, command)
			else:
				matchIt = re.finditer(r"\b%s\b" % self.name, command)
				for match in matchIt:
					# Parse the match
					matchPos = match.start()
					parenthCount = 0
					preBracketFlag = True # Flag to show when the first bracket is found.
					foundString = []
					for char in command[matchPos:]:
						if char == "(":
							parenthCount += 1
							preBracketFlag = False
						elif char == ")":
							parenthCount -= 1
						foundString.append(char)
						if parenthCount == 0 and preBracketFlag == False:
							break
					foundString = "".join(foundString)

					# Check whether the args are valid
					openBracketPos = foundString.find("(")
					if openBracketPos == -1:
						raise ksp_compiler.ParseException(self.line, "No arguments found for define macro: %s" % foundString)
					foundArgs = ksp_compiler.split_args(foundString[openBracketPos + 1 : len(foundString) - 1], self.line)
					if len(foundArgs) != len(self.args):
						raise ksp_compiler.ParseException(self.line, "Incorrect number of arguments in define macro: %s. Expected %d, got %d.\n" % (foundString, len(self.args), len(foundArgs)))

					# Build the new value using the given args
					newVal = self.value
					for arg_idx, arg in enumerate(self.args):
						if arg.startswith("#") and arg.endswith("#"):
							newVal = re.sub(arg, foundArgs[arg_idx], newVal)
						else:
							newVal = re.sub(r"\b%s\b" % arg, foundArgs[arg_idx], newVal)
					newCommand = newCommand.replace(foundString, newVal)
		return(newCommand)

def handleDefineConstants(lines):
	defineConstants = collections.deque()
	newLines = collections.deque()
	for lineIdx in range(len(lines)):
		line = lines[lineIdx].command.strip()
		if line.startswith("define"):
			m = re.search(define_re, line)
			if m:
				defineObj = DefineConstant(m.group("whole"), m.group("val").strip(), m.group("args"), lines[lineIdx])
				defineConstants.append(defineObj)
			else:
				newLines.append(lines[lineIdx])
		else:
			newLines.append(lines[lineIdx])

	if defineConstants:
		# Replace all occurances where other defines are used in define values
		for i in range(len(defineConstants)):
			for j in range(len(defineConstants)):
				defineConstants[i].setValue(defineConstants[j].substituteValue(defineConstants[i].getValue()))
			defineConstants[i].evaluateValue()

		# For each line, replace any places the defines are used
		for lineIdx in range(len(newLines)):
			line = newLines[lineIdx].command
			for defineConst in defineConstants:
				newLines[lineIdx].command = defineConst.substituteValue(newLines[lineIdx].command)
	replaceLines(lines, newLines)

#=================================================================================================
class UIArray(object):
	def __init__(self, name, uiType, size, persistence, familyPrefix, uiParams, line):
		self.name = name
		self.familyPrefix = familyPrefix or ""
		# if not familyPrefix:
		# 	self.familyPrefix = ""
		self.uiType = uiType
		self.prefixSymbol = ""
		if self.uiType == "ui_text_edit":
			self.prefixSymbol = "@"
		self.uiParams = uiParams or ""
		# if not uiParams:
		# 	self.uiParams = ""
		self.numElements = size
		self.dimensionsString = size
		self.underscore = ""
		if "," in size:
			self.underscore = "_"
			self.numElements = "*".join(["(%s)" % dim for dim in size.split(",")])
		self.numElements = try_evaluation(self.numElements, line, "UI array size")
		self.persistence = persistence or ""
		# if not persistence:
		# 	self.persistence = ""

	# Get the command string for declaring the raw ID array
	def getRawArrayDeclaration(self):
		return("declare %s[%s]" % (self.name, self.dimensionsString))

	def buildLines(self, line):
		newLines = collections.deque()
		for i in range(self.numElements):
			uiName = self.underscore + self.name
			text = "declare %s %s %s %s" % (self.persistence, self.uiType, self.prefixSymbol + uiName + str(i), self.uiParams)
			newLines.append(line.copy(text))
			text = "%s[%s] := get_ui_id(%s)" % (self.familyPrefix + uiName, str(i), self.familyPrefix + uiName + str(i))
			newLines.append(line.copy(text))
		return(newLines)

def handle_ui_arrays(lines):
	newLines = collections.deque()
	for lineNum in range(len(lines)):
		line = lines[lineNum].command.strip()
		if line.startswith("decl"): # This might just improve efficiency.
			m = re.search(ui_array_re, line)
			if m:
				famPre = inspect_family_state(lines, lineNum) # TODO: This should be replaced with a fam_count for efficiency
				uiType = m.group("uitype")
				if (uiType == "ui_table" and m.group("tablesize")) or uiType != "ui_table":
					arrayObj = UIArray(m.group("whole"), uiType, m.group("arraysize"), m.group("persistence"), famPre, m.group("uiparams"), lines[lineNum])
					newLines.append(lines[lineNum].copy(arrayObj.getRawArrayDeclaration()))
					newLines.extend(arrayObj.buildLines(lines[lineNum]))
				else:
					newLines.append(lines[lineNum])
			else: 
				newLines.append(lines[lineNum])
		else:
			newLines.append(lines[lineNum])
	replaceLines(lines, newLines)

#=================================================================================================
def handle_literate_macro(lines):
	literal_vals = []
	macro_name = []
	line_numbers = []
	is_single_line = []

	for index in range(len(lines)):
		line = lines[index].command
		if re.search(r"^\s*literate_macro\(", line):
			name = line[line.find("(") + 1 : line.find(")")]
			params = line[line.find(")") + 1:]

			find_n = False
			if "#l#" in name:
				find_n = True
			is_single_line.append(find_n)

			try:
				literal = params[params.find("on") + 2 : ].strip()

			except:
				raise ksp_compiler.ParseException(lines[index], "Incorrect values in literate_macro statement. " + \
						"The macro you are iterating must have only have 1 string parameter, this will be replaced by the value of the defined literal.\n")

			if len(literal):
				macro_name.append(name)
				literal_vals.append(literal.split(","))
				line_numbers.append(index)

			lines[index].command = re.sub(r'[^\r\n]', '', line)

	if line_numbers:
		line_inserts = collections.deque()
		for i in range(len(line_numbers)):
			added_lines = []

			for ii in literal_vals[i]:
				current_text = macro_name[i] + "(" + str(ii) + ")"
				if is_single_line[i]:
					current_text = macro_name[i].replace("#l#", str(ii))
				added_lines.append(lines[line_numbers[i]].copy(current_text))

			line_inserts.append(added_lines)
		replace_lines(lines, line_numbers, line_inserts)

#=================================================================================================
def handle_define_literals(lines):
	define_titles = []
	define_values = []
	define_line_pos = []
	for index in range(len(lines)):
		line = lines[index].command 
		if re.search(r"^\s*define\s+literals\s+", line):
			if re.search(r"^\s*define\s+literals\s+" + varname_re_string + r"\s*:=", line):
				text_without_define = re.sub(r"^\s*define\s+literals\s*", "", line)
				colon_bracket_pos = text_without_define.find(":=")

				# before the assign operator is the title
				title = text_without_define[ : colon_bracket_pos].strip()
				define_titles.append(title)

				# after the assign operator is the value
				value = text_without_define[colon_bracket_pos + 2 : ].strip()
				m = re.search("^\((([a-zA-Z_][a-zA-Z0-9_.]*)?(\s*,\s*[a-zA-Z_][a-zA-Z0-9_.]*)*)\)$", value)
				if not m:
					raise ksp_compiler.ParseException(lines[index], "Syntax error in define literals: Comma separated identifier list in () expected.\n")

				value = m.group(1)
				define_values.append(value)

				define_line_pos.append(index)
				# remove the line
				lines[index].command = re.sub(r'[^\r\n]', '', line)
			else:
				raise ksp_compiler.ParseException(lines[index], "Syntax error in define literals.\n")

	# if at least one define const exsists
	if define_titles:
		# scan the code can replace any occurances of the variable with it's value
		for line_obj in lines:
			line = line_obj.command 
			for index, item in enumerate(define_titles):
				if re.search(r"\b" + item + r"\b", line):
					# character_before = line[line.find(item) - 1 : line.find(item)]  
					# if character_before.isalpha() == False and character_before.isdiget() == False:  
					line_obj.command = line_obj.command.replace(item, str(define_values[index]))
