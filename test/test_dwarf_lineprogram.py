#-------------------------------------------------------------------------------
# elftools tests
#
# Eli Bendersky (eliben@gmail.com)
# This code is in the public domain
#-------------------------------------------------------------------------------
import unittest
from io import BytesIO

from elftools.dwarf.constants import DW_LNS
from elftools.dwarf.lineprogram import LineProgram
from elftools.dwarf.structs import DWARFStructs


class TestLineProgram(unittest.TestCase):
    def _make_program_in_stream(self, stream):
        """ Create a LineProgram from the given program encoded in a stream
        """
        ds = DWARFStructs(little_endian=True, dwarf_format=32, address_size=4)
        header = ds.Dwarf_lineprog_header.parse(
            b'\x04\x10\x00\x00'    # initial length
            b'\x03\x00'            # version
            b'\x20\x00\x00\x00'    # header length
            b'\x01\x01\x01\x0F'    # flags
            b'\x0A'                # opcode_base
            b'\x00\x01\x04\x08\x0C\x01\x01\x01\x00' # standard_opcode_lengths
            # 2 dir names followed by a NULL
            b'\x61\x62\x00\x70\x00\x00'
            # a file entry
            b'\x61\x72\x00\x0C\x0D\x0F'
            # and another entry
            b'\x45\x50\x51\x00\x86\x12\x07\x08'
            # followed by NULL
            b'\x00')

        lp = LineProgram(header, stream, ds, 0, len(stream.getvalue()))
        return lp

    def assertLineState(self, state, **kwargs):
        """ Assert that the state attributes specified in kwargs have the given
            values (the rest are default).
        """
        for k, v in kwargs.items():
            self.assertEqual(getattr(state, k), v)

    def test_spec_sample_59(self):
        # Sample in figure 59 of DWARFv3
        s = BytesIO(
            b'\x02\xb9\x04'
            b'\x0b'
            b'\x38'
            b'\x82'
            b'\x73'
            b'\x02\x02'
            b'\x00\x01\x01')

        lp = self._make_program_in_stream(s)
        linetable = lp.get_entries()

        self.assertEqual(len(linetable), 7)
        self.assertIs(linetable[0].state, None)  # doesn't modify state
        self.assertEqual(linetable[0].command, DW_LNS.advance_pc)
        self.assertEqual(linetable[0].args, [0x239])
        self.assertLineState(linetable[1].state, address=0x239, line=3)
        self.assertEqual(linetable[1].command, 0xb)
        self.assertEqual(linetable[1].args, [2, 0, 0])
        self.assertLineState(linetable[2].state, address=0x23c, line=5)
        self.assertLineState(linetable[3].state, address=0x244, line=6)
        self.assertLineState(linetable[4].state, address=0x24b, line=7, end_sequence=False)
        self.assertEqual(linetable[5].command, DW_LNS.advance_pc)
        self.assertEqual(linetable[5].args, [2])
        self.assertLineState(linetable[6].state, address=0x24d, line=7, end_sequence=True)

    def test_spec_sample_60(self):
        # Sample in figure 60 of DWARFv3
        s = BytesIO(
            b'\x09\x39\x02'
            b'\x0b'
            b'\x09\x03\x00'
            b'\x0b'
            b'\x09\x08\x00'
            b'\x0a'
            b'\x09\x07\x00'
            b'\x0a'
            b'\x09\x02\x00'
            b'\x00\x01\x01')

        lp = self._make_program_in_stream(s)
        linetable = lp.get_entries()

        self.assertEqual(len(linetable), 10)
        self.assertIs(linetable[0].state, None)  # doesn't modify state
        self.assertEqual(linetable[0].command, DW_LNS.fixed_advance_pc)
        self.assertEqual(linetable[0].args, [0x239])
        self.assertLineState(linetable[1].state, address=0x239, line=3)
        self.assertLineState(linetable[3].state, address=0x23c, line=5)
        self.assertLineState(linetable[5].state, address=0x244, line=6)
        self.assertLineState(linetable[7].state, address=0x24b, line=7, end_sequence=False)
        self.assertLineState(linetable[9].state, address=0x24d, line=7, end_sequence=True)

    def test_lne_set_discriminator(self):
        """
        Tests the handling of DWARFv4's new DW_LNE.set_discriminator opcode.
        """
        s = BytesIO()
        s.write(
            b'\x00\x02\x04\x05' +  # DW_LNE.set_discriminator (discriminator=0x05)
            b'\x01' +              # DW_LNS.copy
            b'\x00\x01\x01'        # DW_LNE.end_sequence
        )

        lp = self._make_program_in_stream(s)
        linetable = lp.get_entries()

        # We expect two entries, since DW_LNE.set_discriminator does not add
        # an entry of its own.
        self.assertEqual(len(linetable), 2)
        self.assertEqual(linetable[0].command, DW_LNS.copy)
        self.assertLineState(linetable[0].state, discriminator=0x05)
        self.assertLineState(linetable[1].state, discriminator=0x00, end_sequence=True)

    def test_views(self):
        """ Views disambiguate several rows at the same address.

            The numbering follows GNU readelf/objdump: a row keeps the view
            counter of its address, the counter is bumped after the row is
            emitted, and it is reset whenever the address advances (with the
            exception of DW_LNS_fixed_advance_pc, which does not reset it).
        """
        def set_address(addr):
            return b'\x00\x09\x02' + addr.to_bytes(4, 'little')

        s = BytesIO(
            set_address(0x0) +
            b'\x01' +            # DW_LNS.copy            -> 0x0, view 0
            b'\x01' +            # DW_LNS.copy            -> 0x0, view 1
            set_address(0x1) +   # set Address resets the view
            b'\x01' +            # DW_LNS.copy            -> 0x1, view 0
            b'\x02\x00' +        # DW_LNS.advance_pc 0    -> no reset
            b'\x01' +            # DW_LNS.copy            -> 0x1, view 1
            b'\x02\x01' +        # DW_LNS.advance_pc 1    -> reset
            b'\x01' +            # DW_LNS.copy            -> 0x2, view 0
            b'\x09\x01\x00' +    # DW_LNS.fixed_advance_pc 1 -> no reset
            b'\x01' +            # DW_LNS.copy            -> 0x3, view 1
            b'\x0a' +            # special opcode, +0 PC   -> 0x3, view 2
            b'\x19' +            # special opcode, +1 PC   -> 0x4, view 0
            b'\x01' +            # DW_LNS.copy            -> 0x4, view 1
            b'\x08' +            # DW_LNS.const_add_pc     -> reset
            b'\x01' +            # DW_LNS.copy            -> 0x14, view 0
            set_address(0x100) +
            b'\x00\x01\x01')     # DW_LNE.end_sequence    -> 0x100, view 0

        lp = self._make_program_in_stream(s)
        rows = [e.state for e in lp.get_entries() if e.state is not None]

        self.assertEqual(
            [state.view for state in rows],
            [0, 1, 0, 1, 0, 1, 2, 0, 1, 0, 0])
        self.assertEqual(
            [(state.address, state.view) for state in rows],
            [(0x0, 0), (0x0, 1), (0x1, 0), (0x1, 1), (0x2, 0), (0x3, 1),
             (0x3, 2), (0x4, 0), (0x4, 1), (0x14, 0), (0x100, 0)])

    def test_view_of_first_row_is_zero(self):
        """ The first row of a sequence always opens view 0.
        """
        s = BytesIO(
            b'\x00\x09\x02' + (0x10).to_bytes(4, 'little') +
            b'\x01' +            # DW_LNS.copy -> 0x10, view 0
            b'\x00\x01\x01')     # DW_LNE.end_sequence

        lp = self._make_program_in_stream(s)
        rows = [e.state for e in lp.get_entries() if e.state is not None]

        self.assertEqual([state.view for state in rows], [0, 0])
        self.assertTrue(rows[1].end_sequence)


if __name__ == '__main__':
    unittest.main()
