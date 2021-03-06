"""
This file contains functions that count the connected components in an input mesh.
To run file, enter python connected_components.py DIR_PATH

Author: Nikhil Sharma
"""

import mesh
import sys
import obj_file
import Queue
import os

def assign_components(path):
	"""
	Sets values for component attribute of all meshes in an input directory.
	Utilizes breadth first search to determine connected components and assign values accordingly.
	Returns a dictionary mapping component numbers to indexes of all the vertices contained in that component.

	path -- path to directory containing mesh objects as .obj
	"""
	mesh_files = [filename for filename in os.listdir(path) if filename[-4:] == ".obj"]
	mesh_components_list = []
	for filename in mesh_files:
		print "Assigning components: " + path + "/" + filename
		ob = obj_file.ObjFile(path + "/" + filename)
		mesh = ob.read()
		mesh.remove_unreferenced_vertices()

		# generate graph and connect nodes appropriately
		nodes = []
		for triangle in mesh.triangles():
			node_0 = Node(triangle[0])
			node_1 = Node(triangle[1])
			node_2 = Node(triangle[2])
			node_0.connect_nodes(node_1)
			node_1.connect_nodes(node_2)
			node_2.connect_nodes(node_0)
			nodes.append(node_0)
			nodes.append(node_1)
			nodes.append(node_2)

		# breadth-first-search to mark elements of each component
		component_counter = 0
		component_to_index = {}
		while nodes != []:
			q = Queue.Queue()
			q.put(nodes[0])
			while (q.qsize() != 0):
				curr = q.get()
				curr.visited = True;
				if curr in nodes:
					nodes.remove(curr)
				else:
					continue

				for child in curr.children:
					if not child.visited:
						q.put(child)

				if component_counter in component_to_index:
					if curr.index not in component_to_index[component_counter]:
						component_to_index[component_counter].append(curr.index)
				else:
					component_to_index[component_counter] = [curr.index]
			component_counter += 1
		mesh_components_list.append(component_to_index)
	return mesh_components_list

class Node:
	"""
	A basic Node class used to construct a Graph with the vertices of a given mesh
	"""
	children = []
	visited = False

	def __init__(self, index):
		"""
		Init method for Node class.

		index -- index of vertex in mesh.
		"""
		self.index = index

	def connect_nodes(self, other):
		"""
		Forms a connection between two nodes.

		other -- node to connect this node to.
		"""
		if other not in self.children:
			self.children.append(other)
		# if self not in other.children:
		# 	other.children.append(self)



if __name__ == '__main__':
	print(assign_components(sys.argv[1]))