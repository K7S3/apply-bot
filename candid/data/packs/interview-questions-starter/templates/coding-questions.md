# Coding Interview Questions

A starter set of classic coding interview problems to practice for a {{role}} interview.
For each one, talk through your approach before writing code, then analyze time and space complexity.

## 1. Two Sum

Given an array of integers, return the indices of the two numbers that add up to a target value. Practice the hash-map approach for an O(n) solution.

Source: https://leetcode.com/problems/two-sum/

## 2. Valid Parentheses

Given a string containing brackets, determine whether the brackets are closed in the correct order. A stack-based scan is the standard approach.

Source: https://leetcode.com/problems/valid-parentheses/

## 3. Merge Intervals

Given a collection of intervals, merge all overlapping ones. Sort by start time, then sweep once through the list.

Source: https://leetcode.com/problems/merge-intervals/

## 4. Longest Substring Without Repeating Characters

Given a string, find the length of the longest substring without repeating characters. The sliding-window technique with a character index map works in O(n).

Source: https://leetcode.com/problems/longest-substring-without-repeating-characters/

## 5. Binary Tree Level Order Traversal

Given the root of a binary tree, return the level order traversal of its values, level by level. Breadth-first search with a queue is the natural fit.

Source: https://leetcode.com/problems/binary-tree-level-order-traversal/

## 6. Number of Islands

Given a grid of land and water, count the number of islands. Depth-first or breadth-first flood fill from each unvisited land cell is the classic solution.

Source: https://leetcode.com/problems/number-of-islands/

## 7. LRU Cache

Design a data structure for a least-recently-used cache with O(1) get and put operations. Combine a hash map with a doubly linked list.

Source: https://leetcode.com/problems/lru-cache/

## 8. Group Anagrams

Given an array of strings, group the anagrams together. Hash each string by its sorted characters or character counts.

Source: https://leetcode.com/problems/group-anagrams/
