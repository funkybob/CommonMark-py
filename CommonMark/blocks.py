from __future__ import absolute_import, unicode_literals

import re
from importlib import import_module
from CommonMark import common
from CommonMark.common import unescape_string
from CommonMark.inlines import InlineParser
from CommonMark.node import Node


CODE_INDENT = 4
reHtmlBlockOpen = [
    re.compile(r'.'),  # dummy for 0
    re.compile(r'^<(?:script|pre|style)(?:\s|>|$)', re.IGNORECASE),
    re.compile(r'^<!--'),
    re.compile(r'^<[?]'),
    re.compile(r'^<![A-Z]'),
    re.compile(r'^<!\[CDATA\['),
    re.compile(
        r'^<[/]?(?:address|article|aside|base|basefont|blockquote|body|'
        r'caption|center|col|colgroup|dd|details|dialog|dir|div|dl|dt|'
        r'fieldset|figcaption|figure|footer|form|frame|frameset|h1|head|'
        r'header|hr|html|iframe|legend|li|link|main|menu|menuitem|meta|'
        r'nav|noframes|ol|optgroup|option|p|param|section|source|title|'
        r'summary|table|tbody|td|tfoot|th|thead|title|tr|track|ul)'
        r'(?:\s|[/]?[>]|$)',
        re.IGNORECASE),
    re.compile(
        '^(?:' + common.OPENTAG + '|' + common.CLOSETAG + ')\s*$',
        re.IGNORECASE),
]
reHtmlBlockClose = [
    re.compile(r'.'),  # dummy for 0
    re.compile(r'<\/(?:script|pre|style)>', re.IGNORECASE),
    re.compile(r'-->'),
    re.compile(r'\?>'),
    re.compile(r'>'),
    re.compile(r'\]\]>'),
]
reThematicBreak = re.compile(r'^(?:(?:\* *){3,}|(?:_ *){3,}|(?:- *){3,}) *$')
reMaybeSpecial = re.compile(r'^[#`~*+_=<>0-9-]')
reNonSpace = re.compile(r'[^ \t\f\v\r\n]')
reBulletListMarker = re.compile(r'^[*+-]')
reOrderedListMarker = re.compile(r'^(\d{1,9})([.)])')
reATXHeadingMarker = re.compile(r'^#{1,6}(?: +|$)')
reCodeFence = re.compile(r'^`{3,}(?!.*`)|^~{3,}(?!.*~)')
reClosingCodeFence = re.compile(r'^(?:`{3,}|~{3,})(?= *$)')
reSetextHeadingLine = re.compile(r'^(?:=+|-+) *$')
reLineEnding = re.compile(r'\r\n|\n|\r')


def is_blank(s):
    """Returns True if string contains only space characters."""
    return re.search(reNonSpace, s) is None


def peek(ln, pos):
    if pos < len(ln):
        return ln[pos]
    else:
        return None


def ends_with_blank_line(block):
    """ Returns true if block ends with a blank line,
    descending if needed into lists and sublists."""
    while block:
        if block.last_line_blank:
            return True
        if (block.t == "List" or block.t == "Item"):
            block = block.last_child
        else:
            break

    return False


def parse_list_marker(parser):
    """ Parse a list marker and return data on the marker (type,
    start, delimiter, bullet character, padding) or None."""
    rest = parser.current_line[parser.next_nonspace:]
    data = {
        'type': None,
        'tight': True,  # lists are tight by default
        'bullet_char': None,
        'start': None,
        'delimiter': None,
        'padding': None,
        'marker_offset': parser.indent,
    }
    m = re.match(reBulletListMarker, rest)
    m2 = re.match(reOrderedListMarker, rest)
    if m:
        data['type'] = 'Bullet'
        data['bullet_char'] = m.group()[0]
    elif m2:
        m = m2
        data['type'] = 'Ordered'
        data['start'] = int(m.group(1))
        data['delimiter'] = m.group(2)
    else:
        return None

    # make sure we have spaces after
    nextc = peek(parser.current_line, parser.next_nonspace + len(m.group()))
    if not (nextc is None or nextc == '\t' or nextc == ' '):
        return None

    # we've got a match! advance offset and calculate padding
    parser.advance_next_nonspace()  # to start of marker
    parser.advance_offset(len(m.group()), True)  # to end of marker
    spaces_start_col = parser.column
    spaces_start_offset = parser.offset
    while True:
        parser.advance_offset(1, True)
        nextc = peek(parser.current_line, parser.offset)
        if parser.column - spaces_start_col < 5 and \
           (nextc == ' ' or nextc == '\t'):
            pass
        else:
            break
    blank_item = peek(parser.current_line, parser.offset) is None
    spaces_after_marker = parser.column - spaces_start_col
    if spaces_after_marker >= 5 or \
       spaces_after_marker < 1 or \
       blank_item:
        data['padding'] = len(m.group()) + 1
        parser.column = spaces_start_col
        parser.offset = spaces_start_offset
        if peek(parser.current_line, parser.offset) == ' ':
            parser.advance_offset(1, True)
    else:
        data['padding'] = len(m.group()) + spaces_after_marker

    return data


def lists_match(list_data, item_data):
    """
    Returns True if the two list items are of the same type,
    with the same delimiter and bullet character.  This is used
    in agglomerating list items into lists.
    """
    return list_data.get('type') == item_data.get('type') and \
        list_data.get('delimiter') == item_data.get('delimiter') and \
        list_data.get('bullet_char') == item_data.get('bullet_char')


class Block:
    accepts_lines = None

    @staticmethod
    def continue_(parser=None, container=None):
        return

    @staticmethod
    def finalize(parser=None, block=None):
        return

    @staticmethod
    def can_contain(t):
        return


class Document(Block):
    accepts_lines = False

    @staticmethod
    def continue_(parser=None, container=None):
        return 0

    @staticmethod
    def finalize(parser=None, block=None):
        return

    @staticmethod
    def can_contain(t):
        return t != 'Item'


class List(Block):
    accepts_lines = False

    @staticmethod
    def continue_(parser=None, container=None):
        return 0

    @staticmethod
    def finalize(parser=None, block=None):
        item = block.first_child
        while item:
            # check for non-final list item ending with blank line:
            if ends_with_blank_line(item) and item.nxt:
                block.list_data['tight'] = False
                break
            # recurse into children of list item, to see if there are
            # spaces between any of them:
            subitem = item.first_child
            while subitem:
                if ends_with_blank_line(subitem) and \
                   (item.nxt or subitem.nxt):
                    block.list_data['tight'] = False
                    break
                subitem = subitem.nxt
            item = item.nxt

    @staticmethod
    def can_contain(t):
        return t == 'Item'


class BlockQuote(Block):
    accepts_lines = False

    @staticmethod
    def continue_(parser=None, container=None):
        ln = parser.current_line
        if not parser.indented and peek(ln, parser.next_nonspace) == '>':
            parser.advance_next_nonspace()
            parser.advance_offset(1, False)
            if peek(ln, parser.offset) == ' ':
                parser.offset += 1
        else:
            return 1
        return 0

    @staticmethod
    def finalize(parser=None, block=None):
        return

    @staticmethod
    def can_contain(t):
        return t != 'Item'


class Item(Block):
    accepts_lines = False

    @staticmethod
    def continue_(parser=None, container=None):
        if parser.blank and container.last_child is not None:
            parser.advance_next_nonspace()
        elif parser.indent >= (container.list_data['marker_offset'] +
                               container.list_data['padding']):
            parser.advance_offset(
                container.list_data['marker_offset'] +
                container.list_data['padding'], True)
        else:
            return 1
        return 0

    @staticmethod
    def finalize(parser=None, block=None):
        return

    @staticmethod
    def can_contain(t):
        return t != 'Item'


class Heading(Block):
    accepts_lines = False

    @staticmethod
    def continue_(parser=None, container=None):
        # A heading can never container > 1 line, so fail to match:
        return 1

    @staticmethod
    def finalize(parser=None, block=None):
        return

    @staticmethod
    def can_contain(t):
        return False


class ThematicBreak(Block):
    accepts_lines = False

    @staticmethod
    def continue_(parser=None, container=None):
        # A thematic break can never container > 1 line, so fail to match:
        return 1

    @staticmethod
    def finalize(parser=None, block=None):
        return

    @staticmethod
    def can_contain(t):
        return False


class CodeBlock(Block):
    accepts_lines = True

    @staticmethod
    def continue_(parser=None, container=None):
        ln = parser.current_line
        indent = parser.indent
        if container.is_fenced:
            match = indent <= 3 and \
                len(ln) >= parser.next_nonspace + 1 and \
                ln[parser.next_nonspace] == container.fence_char and \
                re.match(reClosingCodeFence, ln[parser.next_nonspace:])
            if match and len(match.group()) >= container.fence_length:
                # closing fence - we're at end of line, so we can return
                parser.finalize(container, parser.line_number)
                return 2
            else:
                # skip optional spaces of fence offset
                i = container.fence_offset
                while i > 0 and peek(ln, parser.offset) == ' ':
                    parser.advance_offset(1, False)
                    i -= 1
        else:
            # indented
            if indent >= CODE_INDENT:
                parser.advance_offset(CODE_INDENT, True)
            elif parser.blank:
                parser.advance_next_nonspace()
            else:
                return 1
        return 0

    @staticmethod
    def finalize(parser=None, block=None):
        if block.is_fenced:
            # first line becomes info string
            content = block.string_content
            newline_pos = content.index('\n')
            first_line = content[0:newline_pos]
            rest = content[newline_pos + 1:]
            block.info = unescape_string(first_line.strip())
            block.literal = rest
        else:
            # indented
            block.literal = re.sub(r'(\n *)+$', '\n', block.string_content)

        block.string_content = None

    @staticmethod
    def can_contain(t):
        return False


class HtmlBlock(Block):
    accepts_lines = True

    @staticmethod
    def continue_(parser=None, container=None):
        if parser.blank and (container.html_block_type == 6 or
                             container.html_block_type == 7):
            return 1
        else:
            return 0

    @staticmethod
    def finalize(parser=None, block=None):
        if block.string_content == '<div>\n' and \
           block.sourcepos == [[1, 3], [1, 7]]:
            # FIXME :P
            block.string_content = '\n<div>'
        block.literal = re.sub(r'(\n *)+$', '', block.string_content)
        # allow GC
        block.string_content = None

    @staticmethod
    def can_contain(t):
        return False


class Paragraph(Block):
    accepts_lines = True

    @staticmethod
    def continue_(parser=None, container=None):
        return 1 if parser.blank else 0

    @staticmethod
    def finalize(parser=None, block=None):
        has_reference_defs = False

        # try parsing the beginning as link reference definitions:
        while peek(block.string_content, 0) == '[':
            pos = parser.inline_parser.parseReference(
                block.string_content, parser.refmap)
            if not pos:
                break
            block.string_content = block.string_content[pos:]
            has_reference_defs = True
        if has_reference_defs and is_blank(block.string_content):
            block.unlink()

    @staticmethod
    def can_contain(t):
        return False


class BlockStarts:
    """Block start functions.

    Return values:
    0 = no match
    1 = matched container, keep going
    2 = matched leaf, no more block starts
    """
    METHODS = [
        'block_quote',
        'atx_heading',
        'fenced_code_block',
        'html_block',
        'setext_heading',
        'thematic_break',
        'list_item',
        'indented_code_block',
    ]

    @staticmethod
    def block_quote(parser, container=None):
        if not parser.indented and \
           peek(parser.current_line, parser.next_nonspace) == '>':
            parser.advance_next_nonspace()
            parser.advance_offset(1, False)
            # optional following space
            if peek(parser.current_line, parser.offset) == ' ':
                parser.advance_offset(1, False)
            parser.close_unmatched_blocks()
            parser.add_child('BlockQuote', parser.next_nonspace)
            return 1

        return 0

    @staticmethod
    def atx_heading(parser, container=None):
        if not parser.indented:
            m = re.match(reATXHeadingMarker,
                         parser.current_line[parser.next_nonspace:])
            if m:
                parser.advance_next_nonspace()
                parser.advance_offset(len(m.group()), False)
                parser.close_unmatched_blocks()
                container = parser.add_child('Heading', parser.next_nonspace)
                # number of #s
                container.level = len(m.group().strip())
                # remove trailing ###s:
                container.string_content = re.sub(
                    r' +#+ *$', '', re.sub(
                        r'^ *#+ *$', '', parser.current_line[parser.offset:]))
                parser.advance_offset(
                    len(parser.current_line) - parser.offset, False)
                return 2

        return 0

    @staticmethod
    def fenced_code_block(parser, container=None):
        if not parser.indented:
            m = re.match(
                reCodeFence,
                parser.current_line[parser.next_nonspace:])
            if m:
                fence_length = len(m.group())
                parser.close_unmatched_blocks()
                container = parser.add_child('CodeBlock', parser.next_nonspace)
                container.is_fenced = True
                container.fence_length = fence_length
                container.fence_char = m.group()[0]
                container.fence_offset = parser.indent
                parser.advance_next_nonspace()
                parser.advance_offset(fence_length, False)
                return 2

        return 0

    @staticmethod
    def html_block(parser, container=None):
        if not parser.indented and \
           peek(parser.current_line, parser.next_nonspace) == '<':
            s = parser.current_line[parser.next_nonspace:]

            for block_type in range(1, 8):
                if re.search(reHtmlBlockOpen[block_type], s) and \
                   (block_type < 7 or container.t != 'Paragraph'):
                    parser.close_unmatched_blocks()
                    # We don't adjust parser.offset;
                    # spaces are part of the HTML block:
                    b = parser.add_child('HtmlBlock', parser.offset)
                    b.html_block_type = block_type
                    return 2
        return 0

    @staticmethod
    def setext_heading(parser, container=None):
        if not parser.indented and container.t == 'Paragraph':
            m = re.match(
                reSetextHeadingLine,
                parser.current_line[parser.next_nonspace:])
            if m:
                parser.close_unmatched_blocks()
                heading = Node('Heading', container.sourcepos)
                heading.level = 1 if m.group()[0] == '=' else 2
                heading.string_content = container.string_content
                container.insert_after(heading)
                container.unlink()
                parser.tip = heading
                parser.advance_offset(
                    len(parser.current_line) - parser.offset, False)
                return 2

        return 0

    @staticmethod
    def thematic_break(parser, container=None):
        if not parser.indented and re.search(
                reThematicBreak, parser.current_line[parser.next_nonspace:]):
            parser.close_unmatched_blocks()
            parser.add_child('ThematicBreak', parser.next_nonspace)
            parser.advance_offset(
                len(parser.current_line) - parser.offset, False)
            return 2
        return 0

    @staticmethod
    def list_item(parser, container=None):
        if (not parser.indented or container.t == 'List'):
            data = parse_list_marker(parser)
            if data:
                parser.close_unmatched_blocks()

                # add the list if needed
                if parser.tip.t != 'List' or \
                   not lists_match(container.list_data, data):
                    container = parser.add_child('List', parser.next_nonspace)
                    container.list_data = data

                # add the list item
                container = parser.add_child('Item', parser.next_nonspace)
                container.list_data = data
                return 1

        return 0

    @staticmethod
    def indented_code_block(parser, container=None):
        if parser.indented and \
           parser.tip.t != 'Paragraph' and \
                           not parser.blank:
            # indented code
            parser.advance_offset(CODE_INDENT, True)
            parser.close_unmatched_blocks()
            parser.add_child('CodeBlock', parser.offset)
            return 2

        return 0


class Parser:
    def __init__(self, options={}):
        self.doc = Node('Document', [[1, 1], [0, 0]])
        self.block_starts = BlockStarts()
        self.tip = self.doc
        self.oldtip = self.doc
        self.current_line = ''
        self.line_number = 0
        self.offset = 0
        self.column = 0
        self.next_nonspace = 0
        self.next_nonspace_column = 0
        self.indent = 0
        self.indented = False
        self.blank = False
        self.all_closed = True
        self.last_matched_container = self.doc
        self.refmap = {}
        self.last_line_length = 0
        self.inline_parser = InlineParser(options)
        self.options = options

    def break_out_of_lists(self, block):
        """
        Break out of all containing lists, resetting the tip of the
        document to the parent of the highest list, and finalizing
        all the lists.  (This is used to implement the "two blank lines
        break out of all lists" feature.)
        """
        b = block
        last_list = None
        while True:
            if (b.t == "List"):
                last_list = b
            b = b.parent
            if not b:
                break

        if (last_list):
            while block != last_list:
                self.finalize(block, self.line_number)
                block = block.parent
            self.finalize(last_list, self.line_number)
            self.tip = last_list.parent

    def add_line(self):
        """ Add a line to the block at the tip.  We assume the tip
        can accept lines -- that check should be done before calling this."""
        self.tip.string_content += (self.current_line[self.offset:] + '\n')

    def add_child(self, tag, offset):
        """ Add block of type tag as a child of the tip.  If the tip can't
        accept children, close and finalize it and try its parent,
        and so on til we find a block that can accept children."""
        block_class = getattr(import_module('CommonMark.blocks'), self.tip.t)
        while not block_class.can_contain(tag):
            self.finalize(self.tip, self.line_number - 1)
            block_class = getattr(
                import_module('CommonMark.blocks'), self.tip.t)

        column_number = offset + 1
        new_block = Node(tag, [[self.line_number, column_number], [0, 0]])
        new_block.string_content = ''
        self.tip.append_child(new_block)
        self.tip = new_block
        return new_block

    def close_unmatched_blocks(self):
        """Finalize and close any unmatched blocks."""
        if not self.all_closed:
            while self.oldtip != self.last_matched_container:
                parent = self.oldtip.parent
                self.finalize(self.oldtip, self.line_number - 1)
                self.oldtip = parent
            self.all_closed = True

    def find_next_nonspace(self):
        current_line = self.current_line
        i = self.offset
        cols = self.column

        try:
            c = current_line[i]
        except IndexError:
            c = ''
        while c != '':
            if c == ' ':
                i += 1
                cols += 1
            elif c == '\t':
                i += 1
                cols += (4 - (cols % 4))
            else:
                break

            try:
                c = current_line[i]
            except IndexError:
                c = ''

        self.blank = (c == '\n' or c == '\r' or c == '')
        self.next_nonspace = i
        self.next_nonspace_column = cols
        self.indent = self.next_nonspace_column - self.column
        self.indented = self.indent >= CODE_INDENT

    def advance_next_nonspace(self):
        self.offset = self.next_nonspace
        self.column = self.next_nonspace_column

    def advance_offset(self, count, columns):
        cols = 0
        current_line = self.current_line
        try:
            c = current_line[self.offset]
        except IndexError:
            c = None
        while count > 0 and c is not None:
            if c == '\t':
                chars_to_tab = 4 - (self.column % 4)
                self.column += chars_to_tab
                self.offset += 1
                count -= chars_to_tab if columns else 1
            else:
                cols += 1
                self.offset += 1
                # assume ascii; block starts are ascii
                self.column += 1
                count -= 1
            try:
                c = current_line[self.offset]
            except IndexError:
                c = None

    def incorporate_line(self, ln):
        """Analyze a line of text and update the document appropriately.

        We parse markdown text by calling this on each line of input,
        then finalizing the document.
        """
        all_matched = True

        container = self.doc
        self.oldtip = self.tip
        self.offset = 0
        self.column = 0
        self.line_number += 1

        # replace NUL characters for security
        if re.search(r'\u0000', ln) is not None:
            ln = re.sub(r'\0', '\uFFFD', ln)

        self.current_line = ln

        # For each containing block, try to parse the associated line start.
        # Bail out on failure: container will point to the last matching block.
        # Set all_matched to false if not all containers match.
        last_child = container.last_child
        while last_child and last_child.is_open:
            container = last_child

            self.find_next_nonspace()
            block_class = getattr(
                import_module('CommonMark.blocks'), container.t)
            rv = block_class.continue_(self, container)
            if rv == 0:
                # we've matched, keep going
                pass
            elif rv == 1:
                # we've failed to match a block
                all_matched = False
            elif rv == 2:
                # we've hit end of line for fenced code close and can return
                self.last_line_length = len(ln)
                return
            else:
                raise ValueError('returned illegal value, must be 0, 1, or 2')

            if not all_matched:
                # back up to last matching block
                container = container.parent
                break

            last_child = container.last_child

        self.all_closed = (container == self.oldtip)
        self.last_matched_container = container

        # Check to see if we've hit 2nd blank line; if so break out of list:
        if self.blank and container.last_line_blank:
            self.break_out_of_lists(container)
            container = self.tip

        block_class = getattr(import_module('CommonMark.blocks'), container.t)
        matched_leaf = container.t != 'Paragraph' and block_class.accepts_lines
        starts = self.block_starts
        starts_len = len(starts.METHODS)
        # Unless last matched container is a code block, try new container
        # starts, adding children to the last matched container:
        while not matched_leaf:
            self.find_next_nonspace()

            # this is a little performance optimization:
            if not self.indented and \
               not re.search(reMaybeSpecial, ln[self.next_nonspace:]):
                self.advance_next_nonspace()
                break

            i = 0
            while i < starts_len:
                res = getattr(starts, starts.METHODS[i])(self, container)
                if res == 1:
                    container = self.tip
                    break
                elif res == 2:
                    container = self.tip
                    matched_leaf = True
                    break
                else:
                    i += 1

            if i == starts_len:
                # nothing matched
                self.advance_next_nonspace()
                break

        # What remains at the offset is a text line. Add the text to the
        # appropriate container.
        if not self.all_closed and not self.blank and \
           self.tip.t == 'Paragraph':
            # lazy paragraph continuation
            self.add_line()
        else:
            # not a lazy continuation
            # finalize any blocks not matched
            self.close_unmatched_blocks()
            if self.blank and container.last_child:
                container.last_child.last_line_blank = True

            t = container.t

            # Block quote lines are never blank as they start with >
            # and we don't count blanks in fenced code for purposes of
            # tight/loose lists or breaking out of lists.  We also
            # don't set last_line_blank on an empty list item, or if we
            # just closed a fenced block.
            last_line_blank = self.blank and \
                not (t == 'BlockQuote' or
                     (t == 'CodeBlock' and container.is_fenced) or
                     (t == 'Item' and
                      not container.first_child and
                      container.sourcepos[0][0] == self.line_number))

            # propagate last_line_blank up through parents:
            cont = container
            while cont:
                cont.last_line_blank = last_line_blank
                cont = cont.parent

            block_class = getattr(import_module('CommonMark.blocks'), t)
            if block_class.accepts_lines:
                self.add_line()
                # if HtmlBlock, check for end condition
                if t == 'HtmlBlock' and \
                   container.html_block_type >= 1 and \
                   container.html_block_type <= 5 and \
                   re.search(
                       reHtmlBlockClose[container.html_block_type],
                       self.current_line[self.offset:]):
                    self.finalize(container, self.line_number)
            elif self.offset < len(ln) and not self.blank:
                # create a paragraph container for one line
                container = self.add_child('Paragraph', self.offset)
                self.advance_next_nonspace()
                self.add_line()

        self.last_line_length = len(ln)

    def finalize(self, block, line_number):
        """ Finalize a block.  Close it and do any necessary postprocessing,
        e.g. creating string_content from strings, setting the 'tight'
        or 'loose' status of a list, and parsing the beginnings
        of paragraphs for reference definitions.  Reset the tip to the
        parent of the closed block."""
        above = block.parent
        block.is_open = False
        block.sourcepos[1] = [line_number, self.last_line_length]
        block_class = getattr(import_module('CommonMark.blocks'), block.t)
        block_class.finalize(self, block)

        self.tip = above

    def process_inlines(self, block):
        """
        Walk through a block & children recursively, parsing string content
        into inline content where appropriate.
        """
        walker = block.walker()
        self.inline_parser.refmap = self.refmap
        self.inline_parser.options = self.options
        event = walker.nxt()
        while event is not None:
            node = event['node']
            t = node.t
            if not event['entering'] and (t == 'Paragraph' or t == 'Heading'):
                self.inline_parser.parse(node)
            event = walker.nxt()

    def parse(self, my_input):
        """ The main parsing function.  Returns a parsed document AST."""
        self.doc = Node('Document', [[1, 1], [0, 0]])
        self.tip = self.doc
        self.refmap = {}
        self.line_number = 0
        self.last_line_length = 0
        self.offset = 0
        self.column = 0
        self.last_matched_container = self.doc
        self.current_line = ''
        lines = re.split(reLineEnding, my_input)
        length = len(lines)
        if len(my_input) > 0 and my_input[-1] == '\n':
            # ignore last blank line created by final newline
            length -= 1
        for i in range(length):
            self.incorporate_line(lines[i])
        while (self.tip):
            self.finalize(self.tip, length)
        self.process_inlines(self.doc)
        return self.doc
