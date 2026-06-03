"""工作流图测试"""
import pytest
from workflow.graph import build_workflow


def test_build_workflow():
    """测试构建工作流图"""
    workflow = build_workflow()

    assert workflow is not None
    # 检查节点存在
    nodes = workflow.nodes
    assert "parse" in nodes
    assert "filter" in nodes
    assert "judge" in nodes
    assert "review" in nodes
    assert "process_result" in nodes
    assert "split" in nodes
    assert "persist" in nodes


def test_workflow_compile():
    """测试编译工作流"""
    workflow = build_workflow()
    app = workflow.compile()

    assert app is not None


def test_workflow_structure():
    """测试工作流结构"""
    workflow = build_workflow()

    # 检查入口点（通过 __start__ 边）
    assert ("__start__", "parse") in workflow.edges

    # 检查节点数量
    assert len(workflow.nodes) == 7

    # 检查固定边
    assert ("parse", "filter") in workflow.edges
    assert ("judge", "review") in workflow.edges
    assert ("split", "persist") in workflow.edges
    assert ("persist", "__end__") in workflow.edges


def test_conditional_edges():
    """测试条件边"""
    workflow = build_workflow()

    # 检查条件边存在
    conditional_edges = workflow.branches

    # review 节点应该有条件边
    assert "review" in conditional_edges

    # process_result 节点应该有条件边
    assert "process_result" in conditional_edges
