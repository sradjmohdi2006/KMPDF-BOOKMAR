class BookmarkNode:
    """Represents a single node in the PDF outline tree."""
    def __init__(self, title, page_number, children=None):
        self.title = title
        self.page_number = page_number
        self.children = children if children is not None else []
        self.parent = None

        for child in self.children:
            child.parent = self

    def add_child(self, child):
        child.parent = self
        self.children.append(child)
        return child

    def insert_child(self, index, child):
        child.parent = self
        self.children.insert(index, child)
        return child

    def remove_child(self, child):
        if child in self.children:
            self.children.remove(child)
            child.parent = None
            return True
        return False

    def clone(self):
        new_node = BookmarkNode(self.title, self.page_number)
        for child in self.children:
            new_node.add_child(child.clone())
        return new_node


class PDFOutlineModel:
    """Manages the outline tree structure and modifications."""
    def __init__(self):
        self.roots = []

    def clear(self):
        self.roots = []

    def add_root(self, node):
        node.parent = None
        self.roots.append(node)
        return node

    def insert_root(self, index, node):
        node.parent = None
        self.roots.insert(index, node)
        return node

    def remove_node(self, node):
        parent, idx = self.find_parent_and_index(node)
        if idx == -1:
            return False
        if parent is None:
            self.roots.remove(node)
        else:
            parent.remove_child(node)
        return True

    def find_parent_and_index(self, node):
        if node in self.roots:
            return None, self.roots.index(node)

        def search(nodes):
            for parent in nodes:
                if node in parent.children:
                    return parent, parent.children.index(node)
                res = search(parent.children)
                if res[1] != -1:
                    return res
            return None, -1

        return search(self.roots)

    def shift_pages(self, offset, start_page=0):
        def walk(nodes):
            for node in nodes:
                if node.page_number >= start_page:
                    node.page_number = max(0, node.page_number + offset)
                walk(node.children)
        walk(self.roots)

    def move_up(self, node):
        parent, idx = self.find_parent_and_index(node)
        if idx <= 0:
            return False

        siblings = parent.children if parent else self.roots
        siblings[idx], siblings[idx - 1] = siblings[idx - 1], siblings[idx]
        return True

    def move_down(self, node):
        parent, idx = self.find_parent_and_index(node)
        siblings = parent.children if parent else self.roots
        if idx == -1 or idx >= len(siblings) - 1:
            return False

        siblings[idx], siblings[idx + 1] = siblings[idx + 1], siblings[idx]
        return True

    def promote(self, node):
        parent, idx = self.find_parent_and_index(node)
        if parent is None:
            return False

        grandparent, parent_idx = self.find_parent_and_index(parent)
        parent.remove_child(node)

        if grandparent is None:
            self.insert_root(parent_idx + 1, node)
        else:
            grandparent.insert_child(parent_idx + 1, node)
        return True

    def demote(self, node):
        parent, idx = self.find_parent_and_index(node)
        siblings = parent.children if parent else self.roots
        if idx <= 0:
            return False

        predecessor = siblings[idx - 1]
        if parent is None:
            self.roots.remove(node)
        else:
            parent.remove_child(node)

        predecessor.add_child(node)
        return True
