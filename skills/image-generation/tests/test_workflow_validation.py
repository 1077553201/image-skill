"""Pure graph tests: no filesystem fixtures, server or model invocation."""
import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from workflow_validation import validate_capabilities, validate_graph, validate_literal


class CapabilityTests(unittest.TestCase):
    def setUp(self):
        self.config = {'capabilities': {'mode': 'reference_edit', 'model': 'reviewed-local-model',
                        'max_references': 2, 'supported_sizes': [[400, 240]],
                        'validation_evidence': 'Manual synthetic reference-edit test; fidelity needs review.'}}
        self.job = {'width': 400, 'height': 240}

    def test_valid_declaration_returns_independent_record(self):
        result = validate_capabilities(self.config, self.job, 1, 1)
        result['supported_sizes'][0][0] = 1
        self.assertEqual(self.config['capabilities']['supported_sizes'], [[400, 240]])

    def test_missing_fields_and_empty_evidence_rejected(self):
        for name in self.config['capabilities']:
            config = copy.deepcopy(self.config)
            del config['capabilities'][name]
            with self.subTest(field=name), self.assertRaises(ValueError):
                validate_capabilities(config, self.job, 1, 0)
        self.config['capabilities']['validation_evidence'] = '  '
        with self.assertRaises(ValueError):
            validate_capabilities(self.config, self.job, 1, 0)

    def test_references_require_edit_mode_and_capacity(self):
        with self.assertRaises(ValueError):
            validate_capabilities(self.config, self.job, 1, 3)
        self.config['capabilities']['mode'] = 'background'
        with self.assertRaises(ValueError):
            validate_capabilities(self.config, self.job, 1, 1)
        validate_capabilities(self.config, self.job, 1, 0)

    def test_empty_sizes_means_no_support(self):
        self.config['capabilities']['supported_sizes'] = []
        with self.assertRaisesRegex(ValueError, 'dimensions'):
            validate_capabilities(self.config, self.job, 1, 0)

    def test_invalid_sizes_counts_and_booleans_rejected(self):
        for size in ([400], [400, 0], [True, 240], '400x240'):
            config = copy.deepcopy(self.config)
            config['capabilities']['supported_sizes'] = [size]
            with self.subTest(size=size), self.assertRaises(ValueError):
                validate_capabilities(config, self.job, 1, 0)
        for candidates, references in ((True, 0), (0, 0), (1, -1), (1, False)):
            with self.subTest(candidates=candidates, references=references), self.assertRaises(ValueError):
                validate_capabilities(self.config, self.job, candidates, references)


class LiteralTests(unittest.TestCase):
    def test_primitives_and_enum(self):
        for value, declaration in ((12, ['INT']), (1.25, ['FLOAT']), (1, ['FLOAT']),
                                   ('a', ['STRING']), (False, ['BOOLEAN']), ('a', [['a', 'b']])):
            validate_literal(value, declaration, 'input')
        for value, declaration in ((True, ['INT']), (1.5, ['INT']), (True, ['FLOAT']),
                                   ('1', ['FLOAT']), (1, ['STRING']), (1, ['BOOLEAN']),
                                   ('c', [['a', 'b']]), (True, [[0, 1]])):
            with self.subTest(value=value, declaration=declaration), self.assertRaises(ValueError):
                validate_literal(value, declaration, 'input')

    def test_links_are_not_accepted_by_literal_validator(self):
        with self.assertRaises(ValueError):
            validate_literal(['10', 0], ['INT'], 'input')

    def test_finite_bounds_and_steps(self):
        declaration = ['FLOAT', {'min': 0.1, 'max': 1, 'step': 0.1}]
        validate_literal(0.3, declaration, 'input')
        for value in (float('inf'), float('-inf'), float('nan'), 0, 1.1, 0.35):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_literal(value, declaration, 'input')
        validate_literal(9, ['INT', {'min': 1, 'max': 9, 'step': 2}], 'input')
        with self.assertRaises(ValueError):
            validate_literal(8, ['INT', {'min': 1, 'step': 2}], 'input')
        with self.assertRaises(ValueError):
            validate_literal(2**64 - 1, ['INT', {'min': 0, 'step': 2}], 'input')
        for options in ({'step': 0}, {'step': -1}, {'min': 4, 'max': 2}, {'max': float('inf')}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                validate_literal(3, ['INT', options], 'input')


class GraphTests(unittest.TestCase):
    def setUp(self):
        self.info = {
            'Load': {'input': {'required': {'image': ['STRING']}}, 'output': ['IMAGE']},
            'Compose': {'input': {'required': {'image': ['IMAGE'], 'width': ['INT', {'min': 8, 'step': 8}]},
                                  'optional': {'style': [['plain', 'soft']]},
                                  'hidden': {'prompt': 'PROMPT'}}, 'output': ['IMAGE']},
            'Save': {'input': {'required': {'images': ['IMAGE'], 'filename_prefix': ['STRING']}}, 'output': []},
        }
        self.graph = {
            '1': {'class_type': 'Load', 'inputs': {'image': 'approved.png'}},
            '2': {'class_type': 'Compose', 'inputs': {'image': ['1', 0], 'width': 400, 'style': 'plain'}},
            '3': {'class_type': 'Save', 'inputs': {'images': ['2', 0], 'filename_prefix': 'page'}},
        }

    def validate(self, references=('1',)):
        validate_graph(self.graph, self.info, '3', references)

    def test_valid_reference_path_and_optional_input(self):
        self.validate()
        del self.graph['2']['inputs']['style']
        self.validate()

    def test_unused_reference_loader_rejected(self):
        self.graph['4'] = {'class_type': 'Load', 'inputs': {'image': 'unused.png'}}
        with self.assertRaisesRegex(ValueError, 'does not reach'):
            self.validate(('1', '4'))

    def test_unknown_nodes_inputs_hidden_and_missing_required_rejected(self):
        for mutate in (
            lambda: self.graph['1'].update(class_type='NotInstalled'),
            lambda: self.graph['2']['inputs'].update(unknown=1),
            lambda: self.graph['2']['inputs'].update(prompt='external hidden override'),
            lambda: self.graph['2']['inputs'].pop('width'),
        ):
            original = copy.deepcopy(self.graph)
            mutate()
            with self.assertRaises(ValueError):
                self.validate()
            self.graph = original

    def test_bad_source_slots_and_boolean_slots_rejected(self):
        for value in (['404', 0], ['1', -1], ['1', 1], ['1', True]):
            self.graph['2']['inputs']['image'] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.validate()

    def test_link_type_mismatch_and_wildcard(self):
        self.info['Load']['output'] = ['STRING']
        with self.assertRaisesRegex(ValueError, 'type mismatch'):
            self.validate()
        self.info['Load']['output'] = ['*']
        self.validate()
        self.info['Load']['output'] = ['IMAGE']
        self.info['Compose']['input']['required']['image'] = ['*']
        self.validate()

    def test_missing_output_definition_limits_slot_validation(self):
        del self.info['Load']['output']
        self.graph['2']['inputs']['image'] = ['1', 8]
        self.validate()
        self.graph['2']['inputs']['image'] = ['1', -1]
        with self.assertRaises(ValueError):
            self.validate()

    def test_disconnected_cycle_rejected(self):
        self.graph['4'] = {'class_type': 'Compose', 'inputs': {'image': ['4', 0], 'width': 400}}
        with self.assertRaisesRegex(ValueError, 'cycle'):
            self.validate()

    def test_graph_literal_values_are_checked(self):
        self.graph['2']['inputs']['width'] = 401
        with self.assertRaisesRegex(ValueError, 'step'):
            self.validate()

    def test_output_and_reference_ids_must_exist(self):
        with self.assertRaisesRegex(ValueError, 'Missing output'):
            validate_graph(self.graph, self.info, 'missing', ['1'])
        with self.assertRaises(ValueError):
            self.validate(('missing',))
        with self.assertRaisesRegex(ValueError, 'does not reach'):
            self.validate(('3',))


if __name__ == '__main__':
    unittest.main()
