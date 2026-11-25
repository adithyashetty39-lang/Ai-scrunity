"""User-supplied references, transcribed for review; never an approved policy."""
from app.domain import RuleProfile, Submission


def starter_profile() -> RuleProfile:
    return RuleProfile(
        course_code='22CY551', course_name='Artificial Intelligence in Cyber Security',
        syllabus={
            'Module 1': 'Introduction to AI: history, intelligent systems, foundation and subarea of AI, applications, current trend and development of AI. Problem solving: state space search and control strategies, exhaustive searches (Breadth First Search, Depth First Search, Depth first iterative deepening, Travelling salesman problem).',
            'Module 2': 'Problem reduction and Game playing: problem reduction, game playing, bounded look-ahead strategy, alpha-beta pruning, and two player perfect information games.',
            'Module 3': 'Advanced problem solving paradigm: Planning: types of planning system, block world problem, logic based planning, linear planning using a goal stack, means-ends analysis, non linear planning strategies, learning plans.',
            'Module 4': 'Machine learning landscape: what is ML, why, types of ML, main challenges of ML. End to end machine learning project: working with real data, look at the big picture, get the data, discover and visualize the data, prepare the data, select and train the model, fine tune your model.',
            'Module 5': 'Cyber security fundamentals: key concepts, building machine learning model for threat detection, applications of deep learning in cyber security, case studies of AI in cyber security.',
        },
        outcomes={
            'CO1': 'Apply state space search and control strategies for problem solving',
            'CO2': 'Implement algorithms for problem reduction and competitive environments.',
            'CO3': 'Design learning-based strategies for improving the efficiency of planning in AI systems',
            'CO4': 'Apply machine learning techniques to detect and classify cyber security threats.',
        },
        co_po={
            'CO1': {'PO1': 3, 'PO11': 2},
            'CO2': {'PO2': 3, 'PO11': 2},
            'CO3': {'PO4': 3, 'PO5': 2, 'PO11': 2},
            'CO4': {'PO3': 3, 'PO5': 2, 'PO11': 2},
        },
        source_documents=['reference/22CY551-syllabus-reference.png'],
    )


def blank_submission() -> Submission:
    return Submission(title='New paper scrutiny', profile=RuleProfile())
